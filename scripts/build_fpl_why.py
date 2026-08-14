"""WHY-THIS-PICK: yhden virkkeen selitys mallin xP:lle (Claude API, 14.8).

Kehityslista 12.8 (Villen paatos): "mallin komponentit (xG, minuutit, fixture)
yhdeksi selitysvirkkeeksi per pelaaja. Erottaja jota Hubin musta laatikko ei
tehnyt; provenienssi-linja jatkuu."

KOKO SUUNNITTELUN YDIN: selitys EI SAA KEKSIA MITAAN. Malli saa vain
komponentit, ja jokainen tuotettu virke ajetaan LUKUPROVENIENSSIPORTIN lapi:
virkkeessa esiintyva luku joka ei ole faktalohkossa = virke hylataan ja
tilalle tulee deterministinen mallipohjainen lause. Kehotus yksin ei ole
portti — se on toive. Tama on mitattava tarkistus, ja sen negatiivinen
kontrolli on testissa.

Miksi luku eika vaite: hallusinoitu VAITE ("hyva vireessa") on epamaarainen
mutta vaaraton, hallusinoitu LUKU ("6,2 xP") on tarkistettavissa ja tekee
meista valehtelijoita samalla pinnalla jolla myymme tarkistettavuutta.

KUSTANNUKSET
- Batches API = 50 % listahinnasta, ja tama on tyypillinen eraajo (ei
  latenssiherkka): cron ajaa, tulos committoidaan, sivu lukee tiedostoa.
- Cache per GW + komponenttihash: pelaaja regeneroidaan vain jos hanen
  lukunsa ovat oikeasti muuttuneet. Kaytannossa 3 h refresh liikuttaa
  murto-osaa rivesta, joten toinen ajo samalla kierroksella on lahes ilmainen.
- TOP_N rajaa joukon niihin joita kukaan katsoo (xP-jarjestys).

Exit 0 myos kun ei generoitavaa; tekninen virhe -> 1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

XP_PATH = config.PROJECT_ROOT / "data" / "fpl_xp_projections.json"
OUT_PATH = config.PROJECT_ROOT / "data" / "fpl_why.json"

MODEL = "claude-opus-5"
TOP_N = 150
MAX_TOKENS = 2000
POLL_SECONDS = 20
POLL_MAX_MINUTES = 55

# Ajurit ovat SULJETTU LISTA: malli valitsee naista eika keksi omia
# kategorioita. Ilman enumia "why" ajautuisi kausien mittaan eri sanastoon
# eika sita voisi suodattaa tai kaantaa.
DRIVERS = [
    "minutes",          # xMins / aloitustodennakoisyys
    "attacking_output", # viime kauden xGI/90, maalit, syotot
    "fixtures",         # vastustajat horisontissa
    "clean_sheets",     # puolustajat/maalivahdit
    "set_pieces",       # pilkut, kulmat, vapaapotkut
    "bonus",            # odotettu bonus
    "price",            # hinta suhteessa tuotokseen
    "differential",     # matala omistus
]

SYSTEM = """You explain a football model's expected-points projection for one \
player in exactly one sentence, for a fantasy manager deciding whether to pick him.

You are given a FACTS block. That block is the only information that exists. \
Every number you write must appear verbatim in the FACTS block. Do not compute \
new numbers, do not round differently, do not add league context, form \
narratives, injury speculation, transfer rumours, or anything you happen to \
know about the player. If the facts are thin, write a thinner sentence.

Name the one or two things that actually drive the projection and say what they \
mean for the pick. Write it the way a knowledgeable friend would say it out \
loud: plain words, no jargon, no dashes joining clauses, no colon-separated \
label. Do not open with the player's name and do not repeat his expected points \
if the interface already shows it. Do not include internal or system XML tags \
in your response."""

SCHEMA = {
    "type": "object",
    "properties": {
        "sentence": {"type": "string"},
        "drivers": {
            "type": "array",
            "items": {"type": "string", "enum": DRIVERS},
        },
    },
    "required": ["sentence", "drivers"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------
# Faktalohko (puhdas)
# --------------------------------------------------------------------------

def _num(value, ndigits: int = 1):
    try:
        return round(float(value), ndigits)
    except (TypeError, ValueError):
        return None


def player_facts(player: dict, gw: int, horizon: int) -> dict:
    """Mallin komponentit yhdeksi faktalohkoksi.

    Vain kentat jotka ovat oikeasti mallin syotteita tai sen tuotoksia —
    ei mitaan mita malli ei nae, koska selitys lupaa selittaa TAMAN mallin.
    """
    gws = player.get("gameweeks") or []
    this_gw = next((g for g in gws if g.get("gw") == gw), None)
    fixtures = []
    for g in gws[:horizon]:
        for opp in (g.get("opponents") or []):
            fixtures.append(f"{opp.get('opp')} ({opp.get('venue')})")

    last = player.get("last_season") or {}
    per90 = last.get("per90") or {}
    sp = player.get("set_pieces") or {}

    facts = {
        "id": player.get("id"),
        "name": player.get("web_name"),
        "team": player.get("team"),
        "position": player.get("pos"),
        "price_m": _num(player.get("price")),
        "owned_pct": _num(player.get("owned_pct")),
        "xp_this_gw": _num(this_gw.get("xp")) if this_gw else None,
        "xp_next_{}_gws".format(horizon): _num(player.get("xp_horizon_total")),
        "expected_minutes": _num(player.get("xmins"), 0),
        "start_probability_pct": _num(
            100.0 * float(player.get("p_start") or 0.0), 0),
        "minutes_confidence": player.get("minutes_confidence"),
        "expected_bonus": _num(player.get("e_bonus"), 2),
        "next_opponents": fixtures,
        "horizon_gws": horizon,
    }
    if last:
        facts["last_season"] = {
            "minutes": last.get("minutes"),
            "starts": last.get("starts"),
            "goals": last.get("goals"),
            "assists": last.get("assists"),
            "goals_per90": _num(per90.get("goals"), 2),
            "assists_per90": _num(per90.get("assists"), 2),
            "xgi_per90": _num(per90.get("xgi"), 2),
        }
    takers = [k for k in ("pens", "corners", "fk") if sp.get(k)]
    if takers:
        facts["set_piece_duties"] = takers
    if player.get("news"):
        facts["availability_note"] = player["news"]
    return {k: v for k, v in facts.items() if v not in (None, [], {})}


# --------------------------------------------------------------------------
# Lukuprovenienssiportti (puhdas — tama on se joka oikeasti estaa keksimisen)
# --------------------------------------------------------------------------

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _numeric_strings(value, out: set[str]) -> None:
    if isinstance(value, dict):
        for v in value.values():
            _numeric_strings(v, out)
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            _numeric_strings(v, out)
        return
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        f = float(value)
        # 4.50 -> "4.5" ja "4.50" ovat sama luku lukijalle; molemmat sallitaan.
        # Kokonaisluvuksi pyoristaminen EI ole: 5.8 ei saa oikeuttaa "6":tta,
        # koska lukija tarkistaa luvun sivulta jossa lukee 5.8.
        out.add(f"{f:g}")
        out.add(f"{f:.1f}")
        out.add(f"{f:.2f}")
        if f == int(f):
            out.add(str(int(f)))
            out.add(f"{f:.0f}")
        return
    if isinstance(value, str):
        for m in _NUM_RE.findall(value):
            out.add(m.replace(",", "."))


def allowed_numbers(facts: dict) -> set[str]:
    out: set[str] = set()
    _numeric_strings(facts, out)
    return out


# "per 90" on jalkapallodatan vakioyksikko eika vaite, joten se on ainoa
# sallittu luku jota faktalohko ei kanna. Lista on tarkoituksella yhden
# mittainen: jokainen lisays tahan on reika portissa.
UNIT_NUMBERS = {"90"}


def ungrounded_numbers(sentence: str, facts: dict) -> list[str]:
    """Virkkeen luvut jotka EIVAT ole faktalohkossa. Tyhja = puhdas."""
    allowed = allowed_numbers(facts) | UNIT_NUMBERS
    bad = []
    for raw in _NUM_RE.findall(sentence or ""):
        token = raw.replace(",", ".")
        candidates = {token}
        # Perakkaiset nollat karsitaan VAIN desimaaliosasta ("4.50" -> "4.5").
        # Ilman tata ehtoa "90" typistyi "9":ksi ja lapaisi portin milla
        # tahansa pelaajalla jolla oli 9 maalia — portti oli sokea tasan
        # silla tavalla jota se oli rakennettu estamaan.
        if "." in token:
            candidates.add(token.rstrip("0").rstrip(".") or "0")
        try:
            f = float(token)
            candidates |= {f"{f:g}", f"{f:.1f}", f"{f:.2f}"}
            if f == int(f):
                candidates.add(str(int(f)))
        except ValueError:
            pass
        if not (candidates & allowed):
            bad.append(raw)
    return bad


BANNED_SUBSTRINGS = (
    "—",   # em dash (copy-portti koskee myos tata pintaa)
    "–",   # en dash
    "<thinking",
    "<system",
    "odds",     # brandilinja: tuloksiin, ei kertoimiin
)


def sentence_problems(sentence: str, facts: dict) -> list[str]:
    """Kaikki syyt hylata virke. Tyhja lista = kelpaa julkaistavaksi."""
    problems: list[str] = []
    s = (sentence or "").strip()
    if not s:
        return ["tyhja virke"]
    if len(s) > 240:
        problems.append(f"liian pitka ({len(s)} merkkia)")
    if s.count(".") > 2:
        problems.append("useampi kuin yksi virke")
    low = s.lower()
    for bad in BANNED_SUBSTRINGS:
        if bad in low:
            problems.append(f"kielletty merkkijono: {bad!r}")
    bad_nums = ungrounded_numbers(s, facts)
    if bad_nums:
        problems.append("pohjaton luku: " + ", ".join(sorted(set(bad_nums))))
    return problems


def template_sentence(facts: dict) -> str:
    """Deterministinen varalause kun malli hylataan tai ei vastaa.

    EI ole huono lopputulos: se on tarkka ja tylsa. Tyhja kentta olisi
    huonompi kuin tylsa kentta, ja keksitty lause olisi huonompi kuin molemmat.
    """
    mins = facts.get("expected_minutes")
    opponents = facts.get("next_opponents") or []
    bits = []
    if mins is not None:
        bits.append(f"about {mins:g} minutes a game")
    xgi = (facts.get("last_season") or {}).get("xgi_per90")
    if xgi:
        bits.append(f"{xgi:g} expected goal involvements per 90 last season")
    if facts.get("set_piece_duties"):
        bits.append("set piece duties")
    if not bits:
        return "The projection is built from expected minutes and fixtures."
    if len(bits) == 1:
        lead = bits[0]
    else:
        lead = ", ".join(bits[:-1]) + " and " + bits[-1]
    tail = (f", with {', '.join(opponents[:3])} to come" if opponents else "")
    return f"The projection leans on {lead}{tail}."


def component_hash(facts: dict) -> str:
    """Faktalohkon sormenjalki. Sama hash = selitys on yha voimassa.

    Ilman tata jokainen 3 h refresh maksaisi taydet 150 kutsua, vaikka
    valtaosa riveista ei liiku lainkaan.
    """
    blob = json.dumps(facts, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def select_players(payload: dict, gw: int, top_n: int) -> list[dict]:
    """TOP_N pelaajaa taman kierroksen xP-jarjestyksessa."""
    def gw_xp(p: dict) -> float:
        for g in p.get("gameweeks") or []:
            if g.get("gw") == gw:
                return float(g.get("xp") or 0.0)
        return 0.0
    players = [p for p in (payload.get("players") or []) if gw_xp(p) > 0]
    players.sort(key=gw_xp, reverse=True)
    return players[:top_n]


def build_prompt(facts: dict) -> str:
    return ("FACTS\n"
            + json.dumps(facts, indent=1, ensure_ascii=False, sort_keys=True)
            + "\n\nWrite the one-sentence explanation.")


# --------------------------------------------------------------------------
# Claude Batches API
# --------------------------------------------------------------------------

def submit_batch(client, jobs: list[dict]):
    """jobs: [{custom_id, facts}] -> batch-objekti."""
    requests_ = []
    for job in jobs:
        requests_.append({
            "custom_id": job["custom_id"],
            "params": {
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "system": SYSTEM,
                # Matala effort + adaptiivinen ajattelu: tehtava on triviaali
                # eika ajattelusta ole hyotya, mutta ajattelun POIS kytkeminen
                # on Claude Opus 5:lla oma vikaluokkansa (sisaiset tagit
                # vuotavat vastaukseen). Halpa ja turvallinen yhdistelma.
                "thinking": {"type": "adaptive"},
                "output_config": {
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": SCHEMA},
                },
                "messages": [
                    {"role": "user", "content": build_prompt(job["facts"])},
                ],
            },
        })
    return client.messages.batches.create(requests=requests_)


def await_batch(client, batch_id: str):
    deadline = time.monotonic() + POLL_MAX_MINUTES * 60
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            return batch
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"batch {batch_id} ei valmistunut {POLL_MAX_MINUTES} min:ssa")
        print(f"  ...{batch.processing_status} "
              f"(kesken {batch.request_counts.processing})")
        time.sleep(POLL_SECONDS)


def collect_results(client, batch_id: str) -> dict[str, dict]:
    """custom_id -> {"sentence", "drivers"} niille jotka onnistuivat."""
    out: dict[str, dict] = {}
    for result in client.messages.batches.results(batch_id):
        if result.result.type != "succeeded":
            print(f"::warning::{result.custom_id}: {result.result.type}")
            continue
        message = result.result.message
        if message.stop_reason == "refusal":
            print(f"::warning::{result.custom_id}: refusal")
            continue
        text = "".join(b.text for b in message.content if b.type == "text")
        try:
            out[result.custom_id] = json.loads(text)
        except json.JSONDecodeError:
            print(f"::warning::{result.custom_id}: JSON-jasennys epaonnistui")
    return out


def load_existing() -> dict:
    if not OUT_PATH.exists():
        return {"v": 1, "entries": {}}
    try:
        cur = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"v": 1, "entries": {}}
    cur.setdefault("entries", {})
    return cur


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-n", type=int, default=TOP_N)
    ap.add_argument("--dry-run", action="store_true",
                    help="rakenna faktat + varalauseet, ala kutsu APIa")
    args = ap.parse_args()

    if not XP_PATH.exists():
        print(f"::warning::{XP_PATH.name} puuttuu — ohitetaan.")
        return 0
    payload = json.loads(XP_PATH.read_text(encoding="utf-8"))
    meta = payload.get("meta") or {}
    gws = sorted({g.get("gw") for p in (payload.get("players") or [])
                  for g in (p.get("gameweeks") or []) if g.get("gw")})
    if not gws:
        print("::warning::projektiossa ei kierroksia — ohitetaan.")
        return 0
    gw = gws[0]
    horizon = len(gws)

    players = select_players(payload, gw, args.top_n)
    print(f"GW{gw}, horisontti {horizon} kierrosta, {len(players)} pelaajaa")

    store = load_existing()
    entries = store["entries"]
    jobs, facts_by_id = [], {}
    reused = 0
    for p in players:
        facts = player_facts(p, gw, horizon)
        pid = str(facts["id"])
        facts_by_id[pid] = facts
        h = component_hash(facts)
        prev = entries.get(pid)
        if prev and prev.get("hash") == h and prev.get("gw") == gw:
            reused += 1
            continue
        jobs.append({"custom_id": pid, "facts": facts})

    print(f"  cache-osumat {reused}, generoitavia {len(jobs)}")
    if not jobs:
        print("OK: kaikki selitykset ajan tasalla.")
        return 0

    if args.dry_run or not os.environ.get("ANTHROPIC_API_KEY"):
        if not args.dry_run:
            print("::warning::ANTHROPIC_API_KEY puuttuu — kirjoitetaan "
                  "varalauseet (ei virhe).")
        results: dict[str, dict] = {}
    else:
        import anthropic
        client = anthropic.Anthropic()
        batch = submit_batch(client, jobs)
        print(f"  batch {batch.id} lahetetty ({len(jobs)} pyyntoa)")
        batch = await_batch(client, batch.id)
        print(f"  valmis: onnistui {batch.request_counts.succeeded}, "
              f"virhe {batch.request_counts.errored}")
        results = collect_results(client, batch.id)

    n_model, n_template, n_rejected = 0, 0, 0
    for job in jobs:
        pid = job["custom_id"]
        facts = job["facts"]
        parsed = results.get(pid) or {}
        sentence = (parsed.get("sentence") or "").strip()
        drivers = [d for d in (parsed.get("drivers") or []) if d in DRIVERS]
        problems = sentence_problems(sentence, facts) if sentence else ["ei vastausta"]
        if problems:
            if sentence:
                n_rejected += 1
                print(f"::warning::{facts['name']}: hylatty portissa "
                      f"({'; '.join(problems)})")
            sentence = template_sentence(facts)
            source = "template"
            n_template += 1
        else:
            source = "model"
            n_model += 1
        entries[pid] = {
            "gw": gw,
            "hash": component_hash(facts),
            "sentence": sentence,
            "drivers": drivers,
            "source": source,
        }

    store["meta"] = {
        "product": "GoalIQ Fantasy - why this pick",
        "model": MODEL,
        "gw": gw,
        "n_entries": len(entries),
        "generated_from": meta.get("generated_at"),
        "note": ("Explanations are generated from the model's own components. "
                 "Every number is checked against those components before "
                 "publishing; sentences that fail fall back to a template."),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(store, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")
    print(f"OK: {OUT_PATH.name} — mallilta {n_model}, mallipohja {n_template} "
          f"(portti hylkasi {n_rejected}), cache {reused}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — cron-steppi: virhe nakyviin
        print(f"VIRHE: build_fpl_why kaatui: {exc}")
        sys.exit(1)
