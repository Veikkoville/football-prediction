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

SET_PIECE_FIELDS = (
    "penalties_order",
    "direct_freekicks_order",
    "corners_and_indirect_freekicks_order",
)

# Kuinka paljon FPL:n ilmoittama pelitodennakoisyys ja meidan p_start saavat
# poiketa ennen kuin se on erimielisyys. FPL ilmoittaa prosentteina (0-100),
# meidan luku on 0-1.
#
# 0.35 on kalibroitu tunnettuihin tapauksiin eika valittu pyoreana lukuna:
# Kinsky (FPL 100 %, meilla 0.38) ja Dubravka jaavat kiinni, mutta tavallinen
# rotaatioepavarmuus (FPL 75 %, meilla 0.50) ei liputu. Jos tama nostetaan,
# aja `tests/test_squad_signals.py`:n kalibrointitesti uudelleen.
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

        # Laukaisin 2: FPL:n pelitodennakoisyys muuttui JA on eri mielta kuin
        # me. Pelkka muutos ei riita: FPL heiluttaa lukua rutiinilla, ja
        # ilman erimielisyysehtoa tama olisi vahdin aanekkain ja hyodyttomin
        # laukaisin.
        if now.chance_next != before.chance_next and now.chance_next is not None:
            if p_start is not None:
                gap = abs(now.chance_next / 100.0 - p_start)
                if gap >= CHANCE_CONFLICT_THRESHOLD:
                    flags.append(Flag(
                        player_id=pid, web_name=now.web_name,
                        trigger=TRIGGER_CHANCE_CONFLICT,
                        field="chance_of_playing_next_round",
                        before=before.chance_next, after=now.chance_next,
                        owned_pct=owned, our_p_start=p_start,
                        note=f"ero meidan lukuun {gap:.2f}"))

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
