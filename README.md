# Tekoälypohjainen jalkapallon ennustemalli

Kattava, **suomenkielinen** Python-projekti, jossa yhdistetään useampi avoin datalähde
ja koulutetaan ennustemalli ottelutuloksille (1X2), maalimäärille (Over/Under),
tarkalle tulokselle (xG-pohjainen) sekä pelaajatason mittareille.

> **Tavoite-kohderyhmä:** opettelet vasta — projekti on kommentoitu rivi riviltä
> ja muistikirja `notebooks/01_full_pipeline.ipynb` käy koko prosessin läpi.

---

## 1. Datalähteet ja niiden roolit

| Lähde | Mitä tarjoaa | Mihin käytämme | Kirjasto |
|-------|--------------|----------------|----------|
| **StatsBomb Open Data** ([github.com/statsbomb/open-data](https://github.com/statsbomb/open-data)) | Tapahtumatason data (jokainen syöttö, laukaus, painostus): MM-kisat, Messi-data, NWSL, Champions League finaalit | "Ground truth" xG, painostus- ja syöttöverkostot, mallin kalibrointi | `statsbombpy` |
| **FBref** (Sports Reference) | Kausi- ja ottelukohtaiset edistyneet tilastot top-5 liigoille, eurocupeille ja monille muille | Pohjadata — joukkueiden xG, xGA, PPDA, korner- ja kortti-statsit. Suora vienti Pythoniin / Power BI:hin | `soccerdata.FBref` |
| **Understat** | Laukaustason xG kuudelle suurelle liigalle vuodesta 2014 | xG-trendien visualisointi, rolling-form -piirteet | `soccerdata.Understat` |
| **SofaScore** | Live-ottelutiedot, tilastot, momentum | Live-tilanteen seuranta ja in-game -piirteet | `soccerdata.Sofascore` (epävirallinen) |
| **ClubElo** | Joukkueiden Elo-luvut päivätasolla | Vahvuusarvioiden lähtötaso | `soccerdata.ClubElo` |

**Tärkeää:** Käytämme `soccerdata`-kirjastoa, joka on Pieter Robberechtsin avoin
yhteisöprojekti ja hoitaa monimutkaisen scraping-logiikan puolestamme. Lähteiden
käyttöehdot on syytä lukea (etenkin SofaScore — ei kaupalliseen käyttöön ilman lupaa).

---

## 2. Veikkausliiga ja Pohjoismaat

Veikkausliiga ei ole mukana StatsBombin tai Understatin avoimessa datassa.
FBref kattaa Suomen Veikkausliigan ja monet Pohjoismaiset sarjat — käytämme
sitä päälähteenä, ja täydennämme ClubElo:lla. Veikkausliigan osalta
pelaajatason xG-data on rajallisempaa, joten pelaajaennusteet keskittyvät
top-5 liigoihin ja eurocupeihin.

---

## 3. Asennus

```bash
# 1. Luo virtuaaliympäristö
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 2. Asenna riippuvuudet
pip install -r requirements.txt

# 3. Käynnistä Jupyter
jupyter lab
```

Avaa `notebooks/01_full_pipeline.ipynb` ja aja solut järjestyksessä.

---

## 4. Kansiorakenne

```
football-prediction/
├── README.md                     # Tämä tiedosto
├── requirements.txt              # Python-riippuvuudet
├── config.py                     # Asetukset ja vakiot
├── data/
│   ├── raw/                      # Raakadata (ladataan tähän)
│   └── processed/                # Käsitelty data
├── src/
│   ├── data/                     # Datalähde-moduulit
│   │   ├── fbref.py              #   - FBref scraper
│   │   ├── understat.py          #   - Understat xG
│   │   ├── statsbomb.py          #   - StatsBomb open data
│   │   └── sofascore.py          #   - SofaScore live
│   ├── features/                 # Piirteiden rakentaminen
│   │   ├── team_features.py
│   │   └── player_features.py
│   ├── models/                   # Ennustemallit
│   │   ├── dixon_coles.py        #   - Poisson-malli maaleille
│   │   ├── outcome_model.py      #   - 1X2 + O/U gradient boosting
│   │   └── player_model.py       #   - Pelaajatason ennusteet
│   └── viz/
│       └── xg_plots.py           # Understat xG-trendit
├── notebooks/
│   └── 01_full_pipeline.ipynb    # Pää-tutoriaali
└── docs/
    └── arkkitehtuuri.md          # Tekninen arkkitehtuuri
```

---

## 5. Mallien lyhyt kuvaus

### Dixon-Coles Poisson (maalit)
Klassinen jalkapallotilastotieteen kulmakivi: oletetaan että koti- ja
vierasjoukkueen maalit ovat (lähes) Poisson-jakautuneita. Dixon & Coles
(1997) lisäsivät korjaustermin, joka huomioi alhaisten tulosten (0-0, 1-1,
0-1, 1-0) yliedustuksen. Tästä mallista saamme:
- Tarkan tuloksen jakauman
- 1X2-todennäköisyydet (summaamalla)
- Over/Under N maalia (summaamalla)
- BTTS-todennäköisyyden

### Gradient Boosting (1X2 ja O/U)
Vaihtoehtoinen malli, joka käyttää joukkueiden rolling-form -piirteitä
(viime 5 / 10 ottelun keskiarvot xG, xGA, PPDA, …) ja oppii ennustamaan
tuloksen suoraan. Käytämme **LightGBM**iä, koska se on nopea ja toimii
hyvin pienillä-keskisuurilla taulukkodatoilla.

### Pelaajamalli
Yksinkertainen lähtötaso: **per-90 -piirteet** (xG/90, xA/90, kpl/90),
painotettu ekspositiolla (minuutit) ja vastustajan vahvuudella. Tämä on
tutkitusti vahva baseline, jonka päälle voi rakentaa hierarkkisia malleja.

---

## 6. Live-seuranta (SofaScore)

Skriptissä `src/data/sofascore.py` on funktio, joka hakee meneillään olevat
ottelut. Voit ajaa sen vaikka 60 sekunnin välein notebookissa ja päivittää
ennustetta in-game.

> ⚠️ SofaScorella ei ole virallista avointa APIa. `soccerdata`-kirjasto
> käyttää epävirallista reittiä — käytä kohtuudella ja vain henkilökohtaiseen
> kokeiluun.

---

## 7. Power BI -integraatio

FBref-data on tallennettu CSV-muodossa kansioon `data/processed/`.
Power BI:ssä:
1. **Get Data → Folder** ja osoita `data/processed/`
2. Yhdistä tiedostot Power Query:llä
3. Rakenna oma dashboard joukkueittain / liigoittain

Tämä projekti keskittyy itse mallinnukseen — Power BI -dashboard on
seuraava luonnollinen jatko, mutta jätetään lukijan päätöksen varaan
millä KPI:llä alkaa.

---

## 8. Mitä seuraavaksi?

Kun perusversio toimii, kokeile:
- **Bayes-mallit (PyMC):** epävarmuusarviot mukaan
- **Walk-forward CV:** rehellisempi mallin arviointi (ei tulevaa dataa
  menneen ennustamiseen)
- **Vetokerroin-vertailu:** opi kalibroimaan mallin todennäköisyydet
  markkinaa vastaan
- **xT-malli (expected threat):** StatsBomb-tapahtumadatasta
- **Live-momentum -piirre:** SofaScore-momentum-pisteet syötteenä

---

## 9. Vastuuvapauslauseke

Tämä projekti on **opetus- ja tutkimustarkoituksiin**. Vedonlyöntiin
liittyy aina häviön riski — älä lyö enempää kuin olet valmis menettämään,
ja muista että mikään malli ei ole pomminvarma. Suomessa rahapelitoimintaa
säätelee tällä hetkellä Veikkaus, ja vastuullisesta pelaamisesta löytyy
tietoa osoitteessa peluuri.fi.
