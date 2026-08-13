"""Beat the Model V2 vaihe c: Season race -datan kokoaminen (13.8).

Yhdistää mallin gradatut kierrospisteet (data/model_squad_gw_scores.json,
vaihe b) ja käyttäjän oman FPL-historian kumulatiiviseksi eroksi.

MIKSI PALVELIMELLA EIKÄ KLIENTISSÄ (poikkeus speciin, tietoinen):
spec ehdotti kumulatiivisen eron laskemista klientissä, mutta V1-tuloskortin
oma linjaus on *"klientti ei laske pisteitä — se summaa backend-graderin
immutable-tulokset"*, ja klientteja on kaksi (web + mobiili). Sama kaava
kahtena toteutuksena on tasan se rakenne josta 28.7 syntyi kaksi eri lukua
mallin "parhaasta joukkueesta". Yksi lähde, kaksi rendererää.

REHELLISYYS (V1-linja säilyy):
  - Ennen ensimmäistä gradausta ei arvata: available=False + selite siitä
    milloin luvut tulevat.
  - Kierros joka on gradattu mallille mutta puuttuu käyttäjän historiasta
    (esim. liittyi kesken kauden) jätetään eroon laskematta — sitä EI
    tulkita nollaksi, koska nolla olisi väite jota ei tehty.
  - Malli ei pelaa chippejä; se kerrotaan datassa asti (`model_plays_chips`),
    jotta paneelin ei tarvitse päätellä sitä copysta.
"""
from __future__ import annotations

NOTE_NOT_STARTED = ("The model's first squad is locked before the GW1 "
                    "deadline. First scores land once GW1 finishes.")
NOTE_NO_ENTRY = ("Add your FPL team ID to see your own line against the "
                 "model.")


def _user_points_by_gw(entry_history: dict | None) -> dict[int, dict]:
    """FPL entry/{id}/history/ → {gw: {"points": int, "bench": int}}.

    `points` on FPL:n oma kierrospistemäärä siirtokustannusten JÄLKEEN
    (event_transfers_cost sisältyy `points`-kenttään FPL:n omassa
    esityksessä), joten emme korjaa sitä — käyttäjän näkemä luku on se
    jonka hän näkee omalla sivullaan.
    """
    out: dict[int, dict] = {}
    for row in (entry_history or {}).get("current") or []:
        gw = row.get("event")
        if gw is None:
            continue
        out[int(gw)] = {
            "points": int(row.get("points") or 0),
            "bench": int(row.get("points_on_bench") or 0),
            "transfer_cost": int(row.get("event_transfers_cost") or 0),
        }
    return out


def build_race(scores_log: dict | None, entry_history: dict | None,
               premium: bool = True) -> dict:
    """Puhdas ydin: mallin loki + käyttäjän historia → race-payload."""
    rows = list((scores_log or {}).get("gameweeks") or [])
    rows.sort(key=lambda r: int(r.get("gw") or 0))

    if not rows:
        return {
            "meta": {"available": False, "graded_gws": 0, "masked": False,
                     "model_plays_chips": False, "note": NOTE_NOT_STARTED},
            "totals": {"model": 0, "you": None, "diff": None},
            "gameweeks": [],
        }

    user = _user_points_by_gw(entry_history)
    has_entry = entry_history is not None

    out_rows = []
    model_total = 0
    you_total = 0
    cum = 0
    compared = 0
    for r in rows:
        gw = int(r.get("gw") or 0)
        mp = int(r.get("points") or 0)
        model_total += mp
        row = {
            "gw": gw,
            "model_points": mp,
            "fpl_average": r.get("fpl_average"),
            "your_points": None,
            "diff": None,
            "cumulative_diff": None,
        }
        u = user.get(gw)
        if u is not None:
            you_total += u["points"]
            cum += u["points"] - mp
            compared += 1
            row["your_points"] = u["points"]
            row["diff"] = u["points"] - mp
            row["cumulative_diff"] = cum
        if premium:
            # "Missä ero syntyi" — nämä ovat premiumin erittely, eivät
            # kilpailun tulos (free näkee eron, premium sen syyn).
            row["model_captain_id"] = r.get("captain_id")
            row["model_captain_reason"] = r.get("captain_reason")
            row["model_captain_points"] = r.get("captain_points_added")
            row["model_bench_points"] = r.get("bench_points")
            row["model_autosubs"] = r.get("autosubs") or []
            if u is not None:
                row["your_bench_points"] = u["bench"]
                row["your_transfer_cost"] = u["transfer_cost"]
        out_rows.append(row)

    note = None
    if not has_entry:
        note = NOTE_NO_ENTRY
    elif compared == 0:
        note = ("No overlapping gameweeks yet — your history starts after "
                "the model's first graded round.")

    return {
        "meta": {
            "available": True,
            "graded_gws": len(rows),
            "compared_gws": compared,
            "masked": not premium,
            "model_plays_chips": False,
            "note": note,
        },
        "totals": {
            "model": model_total,
            "you": you_total if compared else None,
            "diff": cum if compared else None,
        },
        "gameweeks": out_rows,
    }
