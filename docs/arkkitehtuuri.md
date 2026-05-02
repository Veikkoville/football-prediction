# Tekninen arkkitehtuuri

```
              +--------------------+
              |  StatsBomb open    |
              |  data (GitHub)     |
              +---------+----------+
                        |
                        v
+----------+   +--------+--------+   +---------------+
|  FBref   +-->|  ETL  /         |<--+   Understat   |
| (kausi-/  |   |  yhdistely     |   | (xG, laukauk-|
|  ottelu-) |   |  src/data/*.py |   |  set)         |
+----------+   +--------+--------+   +---------------+
                        |                       ^
                        v                       |
              +---------+--------+              |
              |  Piirreirrotus   |              |
              |  src/features/    |             |
              +---------+--------+              |
                        |                       |
                        v                       |
              +---------+--------+              |
              |  Mallit:         |              |
              |  - Dixon-Coles   |              |
              |  - LightGBM 1X2  |              |
              |  - Pelaaja-baseline             |
              +---------+--------+              |
                        |                       |
                        v                       |
              +---------+--------+    +---------+--------+
              |  Visualisointi   |    |  SofaScore live  |
              |  src/viz/        |    |  pollaus         |
              +------------------+    +------------------+
                        |
                        v
              +---------+--------+
              |  CSV → Power BI  |
              +------------------+
```

## Datavirta

1. **Hae** raw-data soccerdata + statsbombpy -kirjastoilla
2. **Tallenna** välimuisti kansioon `data/raw/`
3. **Yhdistä & kerää piirteet** moduuleilla `src/features/`
4. **Sovita** mallit `src/models/`
5. **Vie** prosessoitu data ja mallin ennusteet kansioon `data/processed/`
6. **Visualisoi** notebookissa tai vie Power BI:hin

## Miksi näin monta lähdettä?

Yksittäinen lähde ei ole täydellinen:

- **FBref** kattaa eniten liigoja (ml. Veikkausliiga), mutta xG perustuu
  Opta/Statsperformin malliin
- **Understat** xG-malli on hieman erilainen ja saatavilla on tarkka
  laukaussijainti — hyvä trendien visualisointiin
- **StatsBomb** xG on alan kultainen standardi, mutta vain MM-kisat,
  finaalit ja Messi-data ovat avoimena
- **SofaScore** ei tarjoa xG:tä, mutta on paras live-tilanteen seurantaan
- **ClubElo** antaa joukkueille pitkäaikaisen vahvuuslukeman, joka
  toimii hyvänä priorina pieni-otoksellisille liigoille

Kun yhdistämme lähteet, saamme rikkaamman piirresetin kuin yhdestäkään
yksin — ja malli on robustimpi yhden lähteen häiriöille.

## Ennusteputki tuotannossa

Kun haluat ajaa mallin uudelle ottelulle:

1. Hae viime N ottelun rolling-piirteet kummallekin joukkueelle (`src/features/`)
2. Aja Dixon-Coles → 1X2 + O/U + tarkat tulokset
3. Aja LightGBM samoilla piirteillä → toinen 1X2-arvio
4. Yhdistä keskiarvolla (50/50) tai oppimalla painotus validointidatalla
5. Tallenna ennuste, vetokerroin (jos vertailu) ja toteutunut tulos
6. Päivitä malli uudelleen joka 1-2 viikko (decay-parametri auttaa)
