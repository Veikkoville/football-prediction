"""PUSH-NOTIF vaiheet b + c: palvelinpushien toimitus (14.8).

Spec: goaliq-app/cos-reports/push-notif-spec-2026-08-13.md

MIKSI b JA c SAMASSA TIEDOSTOSSA: idempotenssi, quiet hours, Expo-batchaus,
receipt-tarkistus ja tokenien siivous ovat samat kaikille kolmelle kanavalle.
Kahtena skriptina ne olisivat kaksi kopiota samasta mekaniikasta, ja niiden
erkaneminen nakyisi vasta tuotannossa (yksi kanava lahettaisi tuplana).

KANAVAT
  deadline_24h / deadline_2h  free    — GW-deadline lahestyy
  price                       premium — watchlistin pelaaja nousemassa
  picks                       premium — mallin viikon poiminta (1x/GW)

IDEMPOTENSSI (specin kova saanto): markkeri kirjoitetaan levylle ENNEN
ensimmainen lahetys, ei sen jalkeen. Cron ajaa 3 h valein ja GitHub-schedule
driftaa; kaatuminen lahetyksen JALKEEN mutta ennen markkerin kirjoitusta
tuottaisi tuplapushin seuraavassa ajossa. Naista kahdesta vikatilasta
"lahetys jai valiin" on kertaluokkaa lievempi kuin "kaikki saivat saman
pushin kahdesti".

IKKUNALOGIIKKA EI NOJAA EDELLISEN AJON KELLOON vaan jaljella olevaan aikaan:
"onko deadlineen alle 26 h" on tosi tai epatosi riippumatta siita milloin
edellinen ajo oli. Aiempi "ylitettiinko raja edellisen ajon jalkeen" -muotoilu
olisi menettanyt ikkunan aina kun ajo jai valiin.

IKKUNAT OVAT LEVEAMMAT KUIN NIMENSA: cron on 3 h valein, joten tasan 2 h
levea ikkuna EI OSU. Esimerkki joka mitattiin ennen kirjoittamista: GW1:n
deadline 17:30 UTC, ajot 15:00 (jaljella 2,5 h) ja 18:00 (mennyt) -> 2 h
-push ei olisi lahtenyt kertaakaan. Siksi ikkuna on 0,25-4,0 h ja teksti
kertoo TODELLISEN jaljella olevan ajan, ei ikkunan nimea.

Exit 0 myos kun ei lahetettavaa. Tekninen virhe -> 1.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import config

STATE_PATH = config.PROJECT_ROOT / "data" / "push_state.json"
PRICE_WATCH_PATH = config.PROJECT_ROOT / "data" / "fpl_price_watch.json"
XP_PATH = config.PROJECT_ROOT / "data" / "fpl_xp_projections.json"

FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_HEADERS = {"User-Agent": "Mozilla/5.0 (GoalIQ push dispatch)"}
EXPO_SEND_URL = "https://exp.host/--/api/v2/push/send"
EXPO_RECEIPT_URL = "https://exp.host/--/api/v2/push/getReceipts"
EXPO_BATCH = 100
HTTP_TIMEOUT = 30

# Deadline-ikkunat tunteina (jaljella oleva aika): (ala, yla].
# 24 h -ikkunan alaraja = 2 h -ikkunan ylaraja, jotta sama ajo ei voi
# tuottaa molempia ja kayttaja saa kaksi pushia minuutin sisalla.
WINDOW_24H = (4.0, 26.0)
WINDOW_2H = (0.25, 4.0)

# Android-kanavat: samat ID:t kuin lib/notifications.ts:ssa. Tuntematon
# channelId putoaa Expolla oletuskanavalle, joten vaara arvo ei riko pushia
# mutta vie sen vaaran kytkimen alle kayttajan asetuksissa.
CHANNEL_DEADLINE = "gw-deadline"
CHANNEL_PRICE = "fpl-price"

QUIET_START_LOCAL = 23   # 23:00 paikallista
QUIET_END_LOCAL = 8      # 08:00 paikallista
DEFAULT_UTC_OFFSET = 3.0

# Differentiaaliraja viikon poiminnalle: yli taman omistusprosentin pelaaja
# ei ole kenellekaan uutinen (sama raja kuin X-postausten kulmassa).
PICK_MAX_OWNED_PCT = 10.0

# Kesaajan mukainen offset-taulu maakoodeille. DST jatetaan tietoisesti
# huomiotta: quiet hours on 9 h levea ikkuna, joten +-1 h virhe siirtaa
# rajaa tunnilla eika voi tuottaa pushia keskella yota. Tarkka
# aikavyohyketietokanta vaatisi tz-datan kantaan, ja meilla on locale.
_REGION_UTC_OFFSET: dict[str, float] = {
    "GB": 1.0, "IE": 1.0, "PT": 1.0, "IS": 0.0, "MA": 1.0,
    "ES": 2.0, "FR": 2.0, "DE": 2.0, "IT": 2.0, "NL": 2.0, "BE": 2.0,
    "SE": 2.0, "NO": 2.0, "DK": 2.0, "PL": 2.0, "CH": 2.0, "AT": 2.0,
    "CZ": 2.0, "HU": 2.0, "ZA": 2.0, "NG": 1.0,
    "FI": 3.0, "EE": 3.0, "LV": 3.0, "LT": 3.0, "GR": 3.0, "RO": 3.0,
    "BG": 3.0, "UA": 3.0, "TR": 3.0, "RU": 3.0, "EG": 3.0,
    "SA": 3.0, "QA": 3.0, "KW": 3.0, "BH": 3.0, "IQ": 3.0, "YE": 3.0,
    "AE": 4.0, "OM": 4.0,
    "IN": 5.5, "PK": 5.0, "BD": 6.0, "TH": 7.0,
    "SG": 8.0, "MY": 8.0, "CN": 8.0, "HK": 8.0, "JP": 9.0, "KR": 9.0,
    "AU": 10.0, "NZ": 12.0,
    "US": -5.0, "CA": -5.0, "MX": -6.0, "BR": -3.0, "AR": -3.0,
}


# --------------------------------------------------------------------------
# Puhtaat funktiot (testattavat ilman verkkoa)
# --------------------------------------------------------------------------

def _now() -> _dt.datetime:
    """Nykyhetki UTC:na omana funktionaan, jotta ikkunalogiikan voi testata
    kelloa siirtamalla ilman etta koko datetime-moduuli patchataan."""
    return _dt.datetime.now(_dt.timezone.utc)


def utc_offset_hours(locale: str | None) -> float:
    """Karkea UTC-offset locale-tagista ('en-GB' -> 1.0).

    Tuntematon tai puuttuva -> DEFAULT_UTC_OFFSET. Perustelu specissa:
    yleiso on RSL + EU, ja +3 on niista konservatiivisin (quiet hours alkaa
    aikaisimmin UTC:ssa mitattuna).
    """
    if not locale or not isinstance(locale, str):
        return DEFAULT_UTC_OFFSET
    parts = locale.replace("_", "-").split("-")
    for part in reversed(parts[1:]):
        code = part.upper()
        if len(code) == 2 and code in _REGION_UTC_OFFSET:
            return _REGION_UTC_OFFSET[code]
    # Kielikoodi ilman maata: ar -> +3 (oletus osuu), en -> oletus.
    return DEFAULT_UTC_OFFSET


def in_quiet_hours(now_utc: _dt.datetime, offset_h: float) -> bool:
    """Onko kayttajan paikallinen kello quiet hours -ikkunassa (23-08)?"""
    local = now_utc + _dt.timedelta(hours=offset_h)
    h = local.hour
    return h >= QUIET_START_LOCAL or h < QUIET_END_LOCAL


def parse_deadline(value: str | None) -> _dt.datetime | None:
    """FPL:n deadline_time ('2026-08-21T17:30:00Z') -> aware datetime."""
    if not value or not isinstance(value, str):
        return None
    try:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def deadline_windows(events: list[dict],
                     now: _dt.datetime) -> list[dict]:
    """Aktiiviset deadline-ikkunat juuri nyt.

    Palauttaa 0-1 alkiota: kaksi ikkunaa eivat voi olla auki samalla
    kierroksella (rajat koskettavat), ja seuraava kierros on aina yli
    26 h paassa edellisen deadlinesta.
    """
    out: list[dict] = []
    for e in events or []:
        if e.get("finished"):
            continue
        dl = parse_deadline(e.get("deadline_time"))
        if dl is None:
            continue
        remaining = (dl - now).total_seconds() / 3600.0
        if WINDOW_2H[0] < remaining <= WINDOW_2H[1]:
            kind = "deadline_2h"
        elif WINDOW_24H[0] < remaining <= WINDOW_24H[1]:
            kind = "deadline_24h"
        else:
            continue
        out.append({
            "gw": int(e.get("id") or 0),
            "kind": kind,
            "remaining_h": remaining,
            "deadline_utc": dl.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    return out


def missed_deadline_windows(events: list[dict], now: _dt.datetime,
                            state: dict) -> list[str]:
    """Ikkunat jotka menivat ohi ilman etta markkeria kirjoitettiin.

    Ilman tata "cron ei ajanut" nayttaa taysin samalta kuin "ei ollut
    lahetettavaa" — eli hiljaiselta onnistumiselta. Sama vikaluokka kuin
    accuracy-login 26 punaista ajoa jotka eivat huutaneet.
    """
    sent = state.get("sent") or {}
    missed: list[str] = []
    for e in events or []:
        dl = parse_deadline(e.get("deadline_time"))
        if dl is None or dl > now:
            continue
        # Vain tuoreet deadlinet: kauden alun kierroksia ei raportoida
        # loputtomiin (ja ennen taman skriptin kayttoonottoa ei ollut mitaan).
        if (now - dl).total_seconds() > 7 * 24 * 3600:
            continue
        gw = int(e.get("id") or 0)
        for kind in ("deadline_24h", "deadline_2h"):
            if marker_key(kind, gw) not in sent:
                missed.append(f"{kind}:gw{gw}")
    return missed


def marker_key(kind: str, gw: int) -> str:
    return f"{kind}:gw{gw}"


def deadline_message(gw: int, remaining_h: float) -> tuple[str, str]:
    """Push-teksti deadlinelle. EI paikallista kelloa (specin kova saanto 4):
    'in N hours' on sama teksti jokaiselle aikavyohykkeelle eika voi vuotaa
    sijaintia kumpaankaan suuntaan."""
    if remaining_h < 1.5:
        when = "in under 90 minutes"
    elif remaining_h < 2.5:
        when = "in about 2 hours"
    else:
        when = f"in about {int(round(remaining_h))} hours"
    title = f"GW{gw} deadline {when}"
    body = ("Check your lineup, captain and transfers before the deadline. "
            "Projections are updated.")
    return title, body


def new_price_risers(watch: dict, already_alerted: dict,
                     today: str) -> list[dict]:
    """Pelaajat jotka ovat NYT rising_soon eivatka ole jo halytettyja.

    Vertailu tehdaan omaan tilatiedostoon eika edelliseen git-committiin
    (spec ehdotti `git show HEAD~1:...`). Syy: dispatch ajetaan samassa
    workflowssa jossa price watch juuri kirjoitettiin mutta committia ei ole
    viela tehty, joten HEAD~1 olisi kahden ajon takainen — ja rebase-retry
    voi vaihtaa HEAD~1:n kokonaan toiseksi commitiksi kesken ajon.
    """
    out: list[dict] = []
    for r in watch.get("risers") or []:
        if r.get("status") != "rising_soon":
            continue
        if r.get("already_changed_today"):
            continue
        pid = str(r.get("id"))
        if already_alerted.get(pid) == today:
            continue
        out.append(r)
    return out


def price_message(rows: list[dict]) -> tuple[str, str]:
    """Push-teksti hinnannousulle. Nimet mahtuvat: max 3 + '+N more'."""
    names = [str(r.get("web_name") or "").strip() for r in rows]
    names = [n for n in names if n]
    if len(names) == 1:
        title = f"{names[0]} is close to a price rise"
    else:
        head = ", ".join(names[:3])
        extra = len(names) - 3
        title = f"{head}{f' +{extra} more' if extra > 0 else ''}: price rise close"
    body = ("Estimated from transfer velocity, not a guarantee. "
            "Open price watch to see how close they are.")
    return title, body


def pick_of_week(xp_payload: dict, gw: int) -> dict | None:
    """Mallin viikon poiminta: korkein taman kierroksen xP alle 10 %
    omistuksella. Sama data ja sama kulma kuin julkisissa postauksissa —
    eri laskenta tarkoittaisi kahta eri 'mallin poimintaa'."""
    best: dict | None = None
    best_xp = 0.0
    for p in xp_payload.get("players") or []:
        try:
            owned = float(p.get("owned_pct") or 0.0)
        except (TypeError, ValueError):
            continue
        if owned > PICK_MAX_OWNED_PCT:
            continue
        xp = 0.0
        for g in p.get("gameweeks") or []:
            if g.get("gw") == gw:
                xp = float(g.get("xp") or 0.0)
                break
        if xp > best_xp:
            best_xp, best = xp, p
    if best is None or best_xp <= 0.0:
        return None
    return {"player": best, "xp": round(best_xp, 2)}


def pick_message(pick: dict, gw: int) -> tuple[str, str]:
    p = pick["player"]
    title = f"GW{gw} model pick: {p.get('web_name')}"
    body = (f"{p.get('team_short')} {p.get('pos')} {p.get('price')}m — "
            f"{pick['xp']} xP this gameweek at {p.get('owned_pct')}% ownership.")
    return title, body


def chunk(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def eligible_tokens(rows: list[dict], channel: str,
                    now: _dt.datetime) -> list[dict]:
    """Suodata opt-in + quiet hours. Palauttaa rivit joille saa lahettaa."""
    flag = {
        "deadline": "opted_in_deadline",
        "price": "opted_in_price",
        "picks": "opted_in_picks",
    }[channel]
    out = []
    for r in rows:
        if not r.get(flag):
            continue
        if in_quiet_hours(now, utc_offset_hours(r.get("locale"))):
            continue
        out.append(r)
    return out


def price_targets(tokens: list[dict], risers: list[dict],
                  last_price_push: dict[str, str],
                  today: str) -> list[tuple[dict, list[dict]]]:
    """(token-rivi, pelaajat) -pareja price-pusheille.

    Kolme porttia: premium-tili, pelaaja kayttajan watchlistissa, ja
    specin kova saanto 1 (max 1 price-push / kayttaja / vrk).

    `is_premium` ja `watchlist` tulevat admin-endpointilta valmiiksi
    liitettyina — runner ei nae profiles-taulua eika tarvitse service-avainta.
    """
    out: list[tuple[dict, list[dict]]] = []
    for t in tokens:
        if not t.get("is_premium"):
            continue
        if last_price_push.get(t["expo_token"]) == today:
            continue
        watchlist = set()
        for pid in (t.get("watchlist") or []):
            try:
                watchlist.add(int(pid))
            except (TypeError, ValueError):
                continue
        if not watchlist:
            continue
        hits = [r for r in risers if int(r.get("id") or 0) in watchlist]
        if hits:
            out.append((t, hits))
    return out


# --------------------------------------------------------------------------
# Tila
# --------------------------------------------------------------------------

def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"v": 1, "sent": {}, "price_alerted": {},
                "last_price_push": {}, "receipts": []}
    try:
        s = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Rikkinainen tila EI saa tuottaa tuplapushia: kaadu nakyvasti.
        raise
    s.setdefault("sent", {})
    s.setdefault("price_alerted", {})
    s.setdefault("last_price_push", {})
    s.setdefault("receipts", [])
    return s


def save_state(state: dict) -> None:
    """Kirjoita tila levylle SYNKRONISESTI.

    fsync on tassa oleellinen eika koristeellinen: markkeri kirjoitetaan
    ennen lahetysta nimenomaan siksi etta prosessin kuolema lahetyksen
    aikana ei tuottaisi tuplaa, ja OS:n kirjoituspuskuriin jaanyt markkeri
    ei olisi olemassa uudelleenkaynnistyksen jalkeen.
    """
    state["updated_at"] = _dt.datetime.now(_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(STATE_PATH)


def prune_state(state: dict, now: _dt.datetime) -> None:
    """Pida tilatiedosto pienena — se committoidaan joka ajossa."""
    cutoff = (now - _dt.timedelta(days=30)).strftime("%Y-%m-%d")
    state["price_alerted"] = {k: v for k, v in state["price_alerted"].items()
                              if v >= cutoff}
    state["last_price_push"] = {k: v for k, v
                                in state["last_price_push"].items()
                                if v >= cutoff}
    keep = {}
    for k, v in (state.get("sent") or {}).items():
        at = (v or {}).get("at") or ""
        if at[:10] >= cutoff:
            keep[k] = v
    state["sent"] = keep


# --------------------------------------------------------------------------
# IO: Supabase / Expo / PostHog
# --------------------------------------------------------------------------

def _admin() -> tuple[str, str] | None:
    """(api_base, admin_token) tai None jos konfiguraatio puuttuu.

    MIKSI ADMIN-API EIKA SUORA SUPABASE (poikkeus speciin, tietoinen):
    spec oletti etta runner lukee push_tokens-taulun service-roolilla. Se
    olisi vaatinut SUPABASE_SERVICE_ROLE_KEYn GitHub-secretiksi — koko
    kannan kirjoitusoikeus CI:hin, jotta voidaan lukea yksi taulu. Render
    pitaa avainta jo hallussaan, ADMIN_TOKEN on jo repo-secret, ja
    /api/admin/grade-decisions on tasan tama kaava. Sivuhyoty: premium- ja
    watchlist-liitos tehdaan palvelimella, joten runner ei nae profiles-
    taulua lainkaan.
    """
    base = os.environ.get("API_BASE", "https://api.goaliq.app").rstrip("/")
    token = os.environ.get("ADMIN_TOKEN", "")
    return (base, token) if base and token else None


def fetch_push_targets() -> list[dict]:
    """Token-rivit premium-lipulla ja watchlistilla valmiiksi liitettyina."""
    adm = _admin()
    if not adm:
        return []
    base, token = adm
    r = requests.get(f"{base}/api/admin/push-targets",
                     headers={"X-Admin-Token": token}, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    rows = (r.json() or {}).get("targets")
    return rows if isinstance(rows, list) else []


def delete_token(token: str) -> None:
    adm = _admin()
    if not adm:
        return
    base, admin_token = adm
    try:
        requests.post(f"{base}/api/admin/push-token-delete",
                      headers={"X-Admin-Token": admin_token},
                      json={"token": token}, timeout=HTTP_TIMEOUT)
        # Vain 12 merkkia lokiin: Expo-token on lahetysoikeus laitteelle,
        # ja GitHub-ajolokit ovat luettavissa laajemmalle joukolle kuin kanta.
        print(f"  siivottu token (DeviceNotRegistered): {token[:12]}...")
    except requests.RequestException as e:
        print(f"::warning::tokenin poisto epaonnistui: {e}")


def expo_send(messages: list[dict]) -> list[dict]:
    """Lahetys Expolle batcheissa. Palauttaa tiketit samassa jarjestyksessa."""
    tickets: list[dict] = []
    for batch in chunk(messages, EXPO_BATCH):
        try:
            r = requests.post(EXPO_SEND_URL, json=batch,
                              headers={"Content-Type": "application/json",
                                       "Accept": "application/json"},
                              timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            data = (r.json() or {}).get("data") or []
        except (requests.RequestException, ValueError) as e:
            print(f"::warning::Expo-lahetys epaonnistui: {e}")
            data = [{"status": "error", "message": str(e)}] * len(batch)
        if len(data) != len(batch):
            data = (list(data) + [{"status": "error",
                                   "message": "missing ticket"}] * len(batch)
                    )[:len(batch)]
        tickets.extend(data)
    return tickets


def check_receipts(state: dict) -> None:
    """Edellisen ajon tiketit -> receiptit. DeviceNotRegistered -> token pois.

    Tehdaan ajon ALUSSA: Expo pyytaa odottamaan ~15 min ennen receiptin
    hakua, ja cron on 3 h valein, joten edellisen ajon tiketit ovat aina
    valmiita. Saman ajon receipteja ei voi hakea.
    """
    pending = state.get("receipts") or []
    if not pending:
        return
    by_id = {p["id"]: p for p in pending if p.get("id")}
    if not by_id:
        state["receipts"] = []
        return
    for ids in chunk(sorted(by_id), 300):
        try:
            r = requests.post(EXPO_RECEIPT_URL, json={"ids": ids},
                              headers={"Content-Type": "application/json"},
                              timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            data = (r.json() or {}).get("data") or {}
        except (requests.RequestException, ValueError) as e:
            print(f"::warning::receipt-haku epaonnistui: {e}")
            continue
        for rid, receipt in (data or {}).items():
            if (receipt or {}).get("status") != "error":
                continue
            details = (receipt or {}).get("details") or {}
            print(f"::warning::push-receipt virhe {rid}: "
                  f"{receipt.get('message')} ({details.get('error')})")
            if details.get("error") == "DeviceNotRegistered":
                tok = (by_id.get(rid) or {}).get("token")
                if tok:
                    delete_token(tok)
    state["receipts"] = []


def posthog_capture(event: str, props: dict) -> None:
    """Fail-soft: mittaus ei saa koskaan kaataa toimitusta."""
    key = os.environ.get("POSTHOG_API_KEY", "")
    if not key:
        return
    host = os.environ.get("POSTHOG_HOST", "https://eu.i.posthog.com")
    try:
        requests.post(f"{host}/capture/", timeout=10, json={
            "api_key": key,
            "event": event,
            "distinct_id": "backend-push-dispatch",
            "properties": {**props, "$lib": "goaliq-push-dispatch"},
        })
    except requests.RequestException:
        pass


def fetch_bootstrap() -> dict:
    r = requests.get(f"{FPL_BASE}/bootstrap-static/", headers=FPL_HEADERS,
                     timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# --------------------------------------------------------------------------
# Lahetys
# --------------------------------------------------------------------------

# Reititys shipatussa bundlessa: App.tsx lukee `data.type` ja vertaa sita
# LOKAALIEN notifikaatioiden sanastoon ('gw_deadline' | 'fpl_price' | ...).
# Tuntematon arvo veisi kayttajan Fixtures-tabiin. Siksi palvelinpush kayttaa
# samaa sanastoa `type`-kentassa — nain reititys toimii ilman appipaivitysta —
# ja `kind` kantaa tarkan kanavan mittausta varten.
ROUTE_TYPE = {
    "deadline_24h": "gw_deadline",
    "deadline_2h": "gw_deadline",
    "price": "fpl_price",
    "picks": "gw_deadline",   # Fantasy-tabi; tarkkuus on `kind`-kentassa
}


def build_message(token_row: dict, title: str, body: str, kind: str,
                  channel_id: str, data: dict | None = None) -> dict:
    return {
        "to": token_row["expo_token"],
        "title": title,
        "body": body,
        "sound": "default",
        "channelId": channel_id,
        "priority": "high",
        "data": {
            "type": ROUTE_TYPE.get(kind, "gw_deadline"),
            "kind": kind,
            "source": "server",
            **(data or {}),
        },
    }


def deliver(messages: list[dict], token_rows: list[dict], kind: str,
            state: dict) -> int:
    """Lahetys + tikettien kirjaus + valittomat DeviceNotRegistered-siivoukset.

    Palauttaa onnistuneiden lukumaaran.
    """
    if not messages:
        return 0
    tickets = expo_send(messages)
    ok = 0
    for row, ticket in zip(token_rows, tickets):
        status = (ticket or {}).get("status")
        if status == "ok" and ticket.get("id"):
            ok += 1
            state["receipts"].append({"id": ticket["id"],
                                      "token": row["expo_token"]})
            continue
        details = (ticket or {}).get("details") or {}
        if details.get("error") == "DeviceNotRegistered":
            delete_token(row["expo_token"])
        else:
            print(f"::warning::push-tiketti virhe ({kind}): "
                  f"{(ticket or {}).get('message')}")
    posthog_capture("push_sent", {"kind": kind, "n_tokens": ok,
                                  "n_attempted": len(messages)})
    print(f"  {kind}: {ok}/{len(messages)} toimitettu Expolle")
    return ok


def main() -> int:
    now = _now()
    today = now.strftime("%Y-%m-%d")
    state = load_state()

    # 1) Edellisen ajon receiptit ennen uusia lahetyksia (token-siivous
    #    ehtii vaikuttaa taman ajon vastaanottajajoukkoon).
    check_receipts(state)

    if not _admin():
        print("::warning::ADMIN_TOKEN puuttuu — pushit OHITETTU (ei virhe). "
              "Lisaa repo-secret (sama arvo kuin Renderin ADMIN_TOKEN).")
        save_state(state)
        return 0

    try:
        tokens = fetch_push_targets()
    except requests.RequestException as e:
        print(f"VIRHE: push-targets-haku epaonnistui: {e}")
        return 1
    print(f"push-targets: {len(tokens)} riviä")

    try:
        boot = fetch_bootstrap()
    except (requests.RequestException, ValueError) as e:
        print(f"VIRHE: FPL bootstrap epaonnistui: {e}")
        return 1
    events = boot.get("events") or []

    for miss in missed_deadline_windows(events, now, state):
        print(f"::warning::deadline-ikkuna {miss} meni ohi ilman lahetysta "
              f"(cron ei ajanut ikkunassa?)")

    windows = deadline_windows(events, now)
    if not windows:
        print("Ei aktiivista deadline-ikkunaa.")

    n_sent = 0
    for w in windows:
        key = marker_key(w["kind"], w["gw"])
        if key in state["sent"]:
            print(f"{key}: jo lahetetty ({state['sent'][key].get('at')}) "
                  f"— ohitetaan.")
            continue

        rows = eligible_tokens(tokens, "deadline", now)
        # MARKKERI ENNEN LAHETYSTA (specin kova saanto).
        state["sent"][key] = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "n_targets": len(rows),
                              "remaining_h": round(w["remaining_h"], 2)}
        save_state(state)

        title, body = deadline_message(w["gw"], w["remaining_h"])
        msgs = [build_message(r, title, body, w["kind"], CHANNEL_DEADLINE,
                              {"gw": w["gw"]}) for r in rows]
        n_sent += deliver(msgs, rows, w["kind"], state)
        save_state(state)

        # Viikon poiminta ratsastaa 24 h -pushin mukana, premiumille, 1x/GW.
        if w["kind"] == "deadline_24h":
            n_sent += dispatch_picks(tokens, w["gw"], now, state)

    n_sent += dispatch_price(tokens, now, today, state)

    prune_state(state, now)
    save_state(state)
    print(f"OK: push_dispatch valmis — {n_sent} pushia lahetetty.")
    return 0


def dispatch_picks(tokens: list[dict], gw: int, now: _dt.datetime,
                   state: dict) -> int:
    key = marker_key("picks", gw)
    if key in state["sent"]:
        return 0
    rows = [r for r in eligible_tokens(tokens, "picks", now)
            if r.get("is_premium")]

    pick = pick_of_week(read_json(XP_PATH), gw)
    if pick is None:
        print("picks: ei differentiaalipoimintaa tälle kierrokselle.")
        return 0

    state["sent"][key] = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "n_targets": len(rows),
                          "player": pick["player"].get("web_name")}
    save_state(state)
    if not rows:
        return 0
    title, body = pick_message(pick, gw)
    msgs = [build_message(r, title, body, "picks", CHANNEL_DEADLINE,
                          {"gw": gw, "player_id": pick["player"].get("id")})
            for r in rows]
    n = deliver(msgs, rows, "picks", state)
    save_state(state)
    return n


def dispatch_price(tokens: list[dict], now: _dt.datetime, today: str,
                   state: dict) -> int:
    watch = read_json(PRICE_WATCH_PATH)
    risers = new_price_risers(watch, state["price_alerted"], today)
    if not risers:
        return 0
    rows = eligible_tokens(tokens, "price", now)
    targets = price_targets(rows, risers, state["last_price_push"], today)
    if not targets:
        return 0

    # MARKKERIT ENNEN LAHETYSTA.
    for row, hits in targets:
        state["last_price_push"][row["expo_token"]] = today
        for h in hits:
            state["price_alerted"][str(h.get("id"))] = today
    save_state(state)

    msgs, rows_out = [], []
    for row, hits in targets:
        title, body = price_message(hits)
        msgs.append(build_message(row, title, body, "price", CHANNEL_PRICE,
                                  {"player_ids": [h.get("id")
                                                  for h in hits]}))
        rows_out.append(row)
    n = deliver(msgs, rows_out, "price", state)
    save_state(state)
    return n


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — cron-steppi: virhe nakyviin
        print(f"VIRHE: push_dispatch kaatui: {exc}")
        sys.exit(1)
