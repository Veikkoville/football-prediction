"""VAIHE 1/3: kausivaihdoksen pelaajavaihtuvuus per joukkue (lahdot JA tulot).

TAUSTA: DC-mallin joukkueluokitukset sovitetaan TOTEUTUNEISIIN tuloksiin, joten
ne eivat nae siirtoikkunaa lainkaan. Esikaudella se on pahimmillaan: 26/27:ssa
ei ole yhtaan ottelua, joten luokitukset pyorivat pelkalla 25/26:lla ja joukkue
on mallissa se joka pelasi viime kauden. Reddit huomasi taman meita ennen
(Newcastle/Thiaw, 9.8.2026).

TAMA SKRIPTI EI VIELA TUOTA YLIAJOJA. Se tuottaa syotteen niille:
  vaihe 1 (tama)  inventaario - kuka lahti, kuka tuli, mika osuus tuotoksesta
  vaihe 2         ulkomaisten tulokkaiden arvottaminen (Understat, liigakorjaus)
  vaihe 3         empiirinen alpha: kuinka paljon nettovaihtuvuus TODELLA siirsi
                  joukkueluokitusta kausivaihdoksissa 22/23->23/24 ->24/25 ->25/26

VAROITUS LUKIJALLE: 'ei PL-dataa' -sarake on sokea piste sokean pisteen sisalla.
Ulkomailta tullut arvotetaan tassa NOLLAKSI, joten netto on ALARAJA joukkueen
vahvuudelle. Ala kayta lukua sellaisenaan - se on puolikas kuva kunnes vaihe 2
on tehty. Sama vikaluokka jonka /fpl/defence teki 8.8: lahtijat listattiin,
tulijat unohtuivat.

Ajo:  python -m scripts.analyze_squad_turnover
"""
import sys, json
sys.path.insert(0, r'C:\Users\vvsaa\Documents\football-prediction')
from collections import defaultdict
import config
RAW = config.RAW_DATA_DIR / "fpl"
old = json.loads((RAW/"bootstrap_static_2526.archive.json").read_text(encoding="utf-8"))
new = json.loads((RAW/"bootstrap_static.json").read_text(encoding="utf-8"))
old_team={t["id"]:t["name"] for t in old["teams"]}; new_team={t["id"]:t["name"] for t in new["teams"]}
old_by_code={e["code"]:e for e in old["elements"]}; id_to_code={e["id"]:e["code"] for e in old["elements"]}
mins,att=defaultdict(float),defaultdict(float)
for f in sorted((RAW/"summary_2526").glob("element_*.json")):
    c=id_to_code.get(int(f.stem.split("_")[1]))
    if c is None: continue
    for r in json.loads(f.read_text(encoding="utf-8")).get("history") or []:
        mins[c]+=min(float(r.get("minutes") or 0),90.0)
        att[c]+=float(r.get("expected_goals") or 0)+float(r.get("expected_assists") or 0)
# 25/26 joukkuetotaalit
tot_att=defaultdict(float); tot_dmin=defaultdict(float)
for c,e in old_by_code.items():
    if mins[c]<=0: continue
    tot_att[old_team[e["team"]]]+=att[c]
    if e["element_type"] in (1,2): tot_dmin[old_team[e["team"]]]+=mins[c]
rows=[]
for tid,tname in new_team.items():
    if tname not in tot_att: continue           # nousija: ei 25/26-PL-vertailukohtaa
    squad_now=[e for e in new["elements"] if e["team"]==tid]
    out_a=out_d=in_a=in_d=0.0; n_unknown=0; in_names=[]
    for c,e in old_by_code.items():
        if old_team[e["team"]]!=tname or mins[c]<=0: continue
        n=next((x for x in squad_now if x["code"]==c),None)
        if n is None:
            out_a+=att[c]
            if e["element_type"] in (1,2): out_d+=mins[c]
    for e in squad_now:
        c=e["code"]; o=old_by_code.get(c)
        if o is not None and old_team[o["team"]]==tname: continue   # jäi
        if o is None or mins[c]<=0:
            n_unknown+=1                                            # ei PL-dataa
            continue
        in_a+=att[c]; in_names.append((att[c],e["web_name"]))
        if e["element_type"] in (1,2): in_d+=mins[c]
    ta,td=tot_att[tname],tot_dmin[tname]
    rows.append((tname,(in_a-out_a)/ta if ta else 0,(in_d-out_d)/td if td else 0,n_unknown,
                 ", ".join(n for _,n in sorted(in_names,reverse=True)[:2]) or "-"))
rows.sort(key=lambda r:r[1])
print(f"{'joukkue':<20}{'NETTO hyokk%':>13}{'NETTO puol.min%':>17}{'ei PL-dataa':>12}  isoimmat tulokkaat (PL-taustalla)")
print("-"*104)
for t,a,d,u,names in rows:
    print(f"{t:<20}{a:+12.1%}{d:+16.1%}{u:>10}   {names}")
