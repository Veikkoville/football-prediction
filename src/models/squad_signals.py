"""SQUAD-SIGNALS-WATCH — vaihe A: paikallinen muutosdiff, ei verkkokutsuja.

Speksi: `cos-reports/squad-signals-watch-spec-2026-08-15.md` (goaliq-app-hubi).

Laukaiseva tapaus 15.8.2026: FPL:n virallinen tili postasi Joao Pedron
kahdesta esikauden maalista, ja meidan aloitustodennakoisyytemme ei
liikkunut lainkaan — se on johdettu VIIME KAUDEN minuuteista, eika mallilla
ole mitaan kanavaa jolla tuo tieto voisi vaikuttaa. Kaksi aiempaa tapausta
(Kinsky, Dubravka) loytyivat sattumalta: Ville luki artikkelin ja kysyi.

TAMA MODUULI EI ENNUSTA MITAAN. Se ei arvioi kuka aloittaa. Se etsii
kohtia joissa SYOTTEEMME on vanhentunut ja pyytaa ihmista katsomaan.
Liputus on kysymys, ei vaite — ja liputus ei ole koskaan postaus.

Kaikki tassa on puhdasta funktiota bootstrap-lumikuvien yli, jotta se on
testattavissa ilman verkkoa. Verkkohaku (vaihe B) ja raportointi ovat
`scripts/squad_signals_watch.py`:ssa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# Laukaisimet 1-5 speksin numeroinnilla. 5 (hintaliike ilman xP-liiketta)
# vaatii xP-historian eika ole viela mukana; se on kirjattu avoimeksi eika
# teeskennella toteutetuksi.
TRIGGER_STATUS = "status"
TRIGGER_CHANCE_CONFLICT = "chance_conflict"
TRIGGER_SET_PIECE = "set_piece_order"
TRIGGER_TRANSFER = "transfer"
TRIGGER_NEW_PLAYER = "new_player"
# 🔴 Laukaisin 8, Villen kysymys 16.8: "kun pelaaja palaa pelikuntoon niin
# xmins yms ymmartaa sen?"
#
# MALLI YMMARTAA: `apply_availability` (`fpl_xp.py`) lukee FPL:n statuksen
# joka buildissa ja palauttaa pelaajan omaan lukuunsa heti kun status on
# taas 'a'. Vastasin taman ensin vaarin ja kirjoitin turhan ohitusrivin,
# joka NOSTI ulkona olevan pelaajan takaisin 0.20:een saatavuusportin jo
# nollattua hanet. Rivi poistettu.
#
# OHITUS EI YMMARRA, ja se on oikea vaara: ohitus ajetaan saatavuusportin
# JALKEEN, joten se on viimeinen sana. Kasin ylos nostettu aloittaja
# (Rushworth 0.90) jaa 0.90:aan vaikka han loukkaantuisi. `review_by` rajaa
# sen kalenteriin, mutta kalenteri ei tieda milloin kukaan loukkaantuu.
#
# Vahdin tehtava on etsia kohtia joissa SYOTTEEMME on vanhentunut. Oma
# ohituksemme on syote siina missa muutkin.
TRIGGER_STALE_OVERRIDE = "stale_override"

SET_PIECE_FIELDS = (
    "penalties_order",
    "direct_freekicks_order",
    "corners_and_indirect_freekicks_order",
)

# 🔴 EHTO ON YKSISUUNTAINEN, ja se korjattiin 16.8 ensimmaisen oikean ajon
# jalkeen. FPL:n `chance_of_playing` on SAATAVUUS; meidan `p_start` on
# ALOITUSTODENNAKOISYYS. Ne eivat ole sama suure, joten symmetrinen vertailu
# tuottaa kohinaa toiseen suuntaan: varamies voi olla 100 % saatavilla ja
# silti aloittaa 10 %:ssa peleista, eika siina ole mitaan ristiriitaa.
#
# Mitattu 16.8 ensimmaisella oikealla ajolla: Meunier (FPL "Knock - 75 %
# chance of playing", meilla 0.10) liputtui, vaikka luvut ovat tasmalleen
# yhteensopivat. Joelinton (FPL 0 % ja "Unspecified injury", meilla 0.54)
# liputtui oikeutetusti.
#
# Aito ristiriita on LOOGINEN RAJOITE: pelaaja ei voi aloittaa useammin kuin
# han on saatavilla. Liputetaan siis vain kun `p_start` YLITTAA saatavuuden.
#
# 🔴 MITA TAMA OIKEASTI MITTAA (tarkennettu 16.8): `apply_availability`
# (`fpl_xp.py`) lukee saatavuuden JOKA BUILDISSA ja nollaa i/s/u/n-pelaajat,
# joten malli EI ole eri mielta FPL:n kanssa pitkaan. Tama laukaisin
# vertaa live-saatavuutta VIIMEKSI RAKENNETTUUN artefaktiin, eli se kertoo
# etta julkaistu luku on vanhentunut suhteessa uutiseen ja builderi pitaa
# ajaa. Se on hyodyllinen signaali, mutta se ei ole mallivirhe. Luulin
# ensin etta saatavuus ei syota minuuttimallia lainkaan; se oli vaarin
# koodia vasten, ja ehdin kirjoittaa sen ohitusrivin perusteluun.
#
# Vastasuunta (FPL korkea, meidan p_start matala) EI ole ristiriita vaan
# tavallinen varamies. Se kuuluu markkinaerimielisyys-laukaisimille 6 ja 7
# (omistus vs. meidan luku), joita ei ole viela rakennettu. Kinsky-tapaus
# 14.8 oli tasan sita lajia — 19,5 %:n omistus ja matala p_start — eika
# tata laukaisinta, ja se oli aiemmin merkitty tanne vaarin.
CHANCE_CONFLICT_THRESHOLD = 0.35


@dataclass
class Flag:
    """Yksi liputus. `before`/`after` ovat aina raakoja arvoja, jotta raportti
    voi nayttaa mika muuttui eika vain etta jokin muuttui."""

    player_id: int
    web_name: str
    trigger: str
    field: str
    before: Any
    after: Any
    owned_pct: float | None = None
    our_p_start: float | None = None
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "web_name": self.web_name,
            "trigger": self.trigger,
            "field": self.field,
            "before": self.before,
            "after": self.after,
            "owned_pct": self.owned_pct,
            "our_p_start": self.our_p_start,
            "note": self.note,
        }


@dataclass
class SnapshotPlayer:
    """Se osa bootstrapin elementista jota vahti seuraa. Tarkoituksella
    kapea: lumikuva kirjoitetaan levylle joka paiva, eika koko bootstrapia
    (587 pelaajaa x ~90 kenttaa) kannata sailoa muutosvahtia varten."""

    id: int
    web_name: str
    team: int
    status: str
    news_added: str | None
    chance_next: int | None
    now_cost: int
    penalties_order: int | None
    direct_freekicks_order: int | None
    corners_and_indirect_freekicks_order: int | None

    @classmethod
    def from_element(cls, e: dict) -> "SnapshotPlayer":
        return cls(
            id=int(e["id"]),
            web_name=e.get("web_name") or "",
            team=int(e.get("team") or 0),
            status=e.get("status") or "",
            news_added=e.get("news_added"),
            chance_next=e.get("chance_of_playing_next_round"),
            now_cost=int(e.get("now_cost") or 0),
            penalties_order=e.get("penalties_order"),
            direct_freekicks_order=e.get("direct_freekicks_order"),
            corners_and_indirect_freekicks_order=e.get(
                "corners_and_indirect_freekicks_order"),
        )

    def as_dict(self) -> dict:
        return {
            "id": self.id, "web_name": self.web_name, "team": self.team,
            "status": self.status, "news_added": self.news_added,
            "chance_next": self.chance_next, "now_cost": self.now_cost,
            "penalties_order": self.penalties_order,
            "direct_freekicks_order": self.direct_freekicks_order,
            "corners_and_indirect_freekicks_order":
                self.corners_and_indirect_freekicks_order,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SnapshotPlayer":
        return cls(
            id=int(d["id"]), web_name=d.get("web_name") or "",
            team=int(d.get("team") or 0), status=d.get("status") or "",
            news_added=d.get("news_added"), chance_next=d.get("chance_next"),
            now_cost=int(d.get("now_cost") or 0),
            penalties_order=d.get("penalties_order"),
            direct_freekicks_order=d.get("direct_freekicks_order"),
            corners_and_indirect_freekicks_order=d.get(
                "corners_and_indirect_freekicks_order"),
        )


@dataclass
class Snapshot:
    """Paivan lumikuva. `taken_at` on kutsujan antama, koska tama moduuli ei
    lue kelloa — se pitaa diffin deterministisena testeissa."""

    taken_at: str
    players: dict[int, SnapshotPlayer] = field(default_factory=dict)

    @classmethod
    def from_bootstrap(cls, bootstrap: dict, taken_at: str) -> "Snapshot":
        players = {}
        for e in bootstrap.get("elements", []):
            p = SnapshotPlayer.from_element(e)
            players[p.id] = p
        return cls(taken_at=taken_at, players=players)

    def as_dict(self) -> dict:
        return {
            "taken_at": self.taken_at,
            "players": [p.as_dict() for p in self.players.values()],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Snapshot":
        players = {}
        for row in d.get("players", []):
            p = SnapshotPlayer.from_dict(row)
            players[p.id] = p
        return cls(taken_at=d.get("taken_at") or "", players=players)


def _projection_index(projections: dict | None) -> dict[int, dict]:
    if not projections:
        return {}
    out = {}
    for row in projections.get("players", []) or []:
        try:
            out[int(row["id"])] = row
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _our_p_start(row: dict | None) -> float | None:
    """Meidan aloitustodennakoisyys 0-1. Artefaktissa kentta on
    `predicted_starts` prosentteina."""
    if not row:
        return None
    v = row.get("predicted_starts")
    if v is None:
        return None
    try:
        return round(float(v) / 100.0, 4)
    except (TypeError, ValueError):
        return None


def diff_signals(
    prev: Snapshot | None,
    curr: Snapshot,
    projections: dict | None = None,
    team_names: dict[int, str] | None = None,
) -> list[Flag]:
    """Laukaisimet 1-4 kahden lumikuvan valilla.

    `prev is None` (ensimmainen ajo) -> **nolla liputusta**. Ensimmainen ajo
    ei ole muutos; jos se liputtaisi koko rosterin, vahti nayttaisi
    valppaalta ja olisi pelkkaa kohinaa. Kirjattu speksin lukuun 5.
    """
    if prev is None:
        return []

    proj = _projection_index(projections)
    names = team_names or {}
    flags: list[Flag] = []

    for pid, now in curr.players.items():
        row = proj.get(pid)
        owned = None
        if row is not None:
            try:
                owned = float(row.get("owned_pct"))
            except (TypeError, ValueError):
                owned = None
        p_start = _our_p_start(row)
        before = prev.players.get(pid)

        # Laukaisin 4b: uusi pelaaja rosterissa.
        if before is None:
            flags.append(Flag(
                player_id=pid, web_name=now.web_name,
                trigger=TRIGGER_NEW_PLAYER, field="id",
                before=None, after=names.get(now.team, now.team),
                owned_pct=owned, our_p_start=p_start,
                note="uusi pelaaja FPL-rosterissa"))
            continue

        # Laukaisin 1: saatavuus. `news_added` mukana, koska status voi pysya
        # samana kun uutinen tarkentuu (esim. "knock" -> "out for 3 weeks").
        if now.status != before.status:
            flags.append(Flag(
                player_id=pid, web_name=now.web_name,
                trigger=TRIGGER_STATUS, field="status",
                before=before.status, after=now.status,
                owned_pct=owned, our_p_start=p_start))
        elif now.news_added and now.news_added != before.news_added:
            flags.append(Flag(
                player_id=pid, web_name=now.web_name,
                trigger=TRIGGER_STATUS, field="news_added",
                before=before.news_added, after=now.news_added,
                owned_pct=owned, our_p_start=p_start,
                note="uusi uutinen, status ennallaan"))

        # Laukaisin 2: FPL:n saatavuus muuttui JA meidan aloitusluku ylittaa
        # sen. Kaksi ehtoa, molemmat tarpeen:
        #   - pelkka muutos ei riita (FPL heiluttaa lukua rutiinilla)
        #   - vertailu on YKSISUUNTAINEN, ks. CHANCE_CONFLICT_THRESHOLD
        if now.chance_next != before.chance_next and now.chance_next is not None:
            if p_start is not None:
                excess = p_start - now.chance_next / 100.0
                if excess >= CHANCE_CONFLICT_THRESHOLD:
                    flags.append(Flag(
                        player_id=pid, web_name=now.web_name,
                        trigger=TRIGGER_CHANCE_CONFLICT,
                        field="chance_of_playing_next_round",
                        before=before.chance_next, after=now.chance_next,
                        owned_pct=owned, our_p_start=p_start,
                        note=f"julkaistu aloitusluku ylittaa saatavuuden "
                             f"{excess:.2f}:lla; aja builderi"))

        # Laukaisin 3: erikoistilannejarjestys. Jokainen liike on suoraan
        # pisteita, joten tassa EI ole omistus- tai kynnyssuodatinta.
        for f in SET_PIECE_FIELDS:
            b, a = getattr(before, f), getattr(now, f)
            if b != a:
                flags.append(Flag(
                    player_id=pid, web_name=now.web_name,
                    trigger=TRIGGER_SET_PIECE, field=f,
                    before=b, after=a,
                    owned_pct=owned, our_p_start=p_start))

        # Laukaisin 4a: siirto.
        if now.team != before.team:
            flags.append(Flag(
                player_id=pid, web_name=now.web_name,
                trigger=TRIGGER_TRANSFER, field="team",
                before=names.get(before.team, before.team),
                after=names.get(now.team, now.team),
                owned_pct=owned, our_p_start=p_start,
                note="joukkue vaihtui"))

    flags.sort(key=lambda f: (-(f.owned_pct or 0.0), f.web_name, f.trigger))
    return flags


def stale_override_flags(
    curr: Snapshot,
    overrides: dict[int, tuple[float, bool]],
    projections: dict | None = None,
) -> list[Flag]:
    """Ohitukset jotka nykytieto on ohittanut.

    `overrides` on {player_id: (p_start, until_available)} CSV:sta.

    Kaksi suuntaa, ja MOLEMMAT ovat ratchetteja jos niita ei valvota:

    - **Ehdollinen alaspain painava rivi, mutta pelaaja on taas saatavilla.**
      Vain `until_available`-riveille: varamiesrivi (Dubravka 0.08) on matala
      koska han ei aloita, EI koska han olisi ulkona, eika se saa purkautua
      saatavuuden perusteella. Liputin ne kerran vaarin.
    - **Ohitus nostaa ylos, mutta pelaaja on ulkona.** Peilikuva: kasin
      nostettu aloittaja joka loukkaantuu jaa yliarvioiduksi.

    Tama EI vertaa ohitusta malliin vaan ohitusta SAATAVUUTEEN. Ohituksen
    koko tarkoitus on olla eri mielta kuin malli, joten mallivertailu
    liputtaisi jokaisen rivin joka paiva.
    """
    proj = _projection_index(projections)
    out: list[Flag] = []
    for pid, (forced, conditional) in overrides.items():
        now = curr.players.get(pid)
        if now is None:
            continue
        row = proj.get(pid)
        owned = None
        if row is not None:
            try:
                owned = float(row.get("owned_pct"))
            except (TypeError, ValueError):
                owned = None
        available = now.status == "a" and (
            now.chance_next is None or now.chance_next >= 75)
        unavailable = now.status in {"i", "s", "u"} or (
            now.chance_next is not None and now.chance_next <= 25)

        if conditional and forced <= 0.35 and available:
            out.append(Flag(
                player_id=pid, web_name=now.web_name,
                trigger=TRIGGER_STALE_OVERRIDE, field="p_start_override",
                before=forced, after="available",
                owned_pct=owned, our_p_start=forced,
                note="ohitus painaa alas mutta pelaaja on taas saatavilla; "
                     "poista tai nosta rivi"))
        elif forced >= 0.65 and unavailable:
            out.append(Flag(
                player_id=pid, web_name=now.web_name,
                trigger=TRIGGER_STALE_OVERRIDE, field="p_start_override",
                before=forced, after=f"status {now.status}/{now.chance_next}",
                owned_pct=owned, our_p_start=forced,
                note="ohitus nostaa ylos mutta pelaaja on ulkona; "
                     "laske tai poista rivi"))
    out.sort(key=lambda f: (-(f.owned_pct or 0.0), f.web_name))
    return out


def team_name_map(bootstrap: dict) -> dict[int, str]:
    out = {}
    for t in bootstrap.get("teams", []) or []:
        try:
            out[int(t["id"])] = t.get("short_name") or t.get("name") or str(t["id"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def summarise(flags: Iterable[Flag]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in flags:
        counts[f.trigger] = counts.get(f.trigger, 0) + 1
    return counts
