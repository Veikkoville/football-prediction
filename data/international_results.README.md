# international_results.csv — vendoroitu maaotteludata (#79)

WC-mallin (`/api/predict-wc`) treenidata kaikkien 48 WC 2026 -maan tuoreista
maaotteluista (WC-karsinnat, Nations League, konfederaatiokisat, friendlyt).

## Lähde

- **Repo:** https://github.com/martj42/international_results
- **Raaka-CSV:** https://raw.githubusercontent.com/martj42/international_results/master/results.csv
- **Lisenssi:** CC0-1.0 (public domain) → vapaa kaupalliseen käyttöön, ei attribuutiopakkoa.
- **Snapshot otettu:** 2026-06-06

## Miksi vendoroitu (ei live-pullia)

Render buildaa gitistä. Data ladataan **build-aikaan committina**, EI serving-polussa
— ei verkkoriippuvuutta eikä cold-start-latenssia pyynnöissä. Snapshot virkistetään
manuaalisesti ennen deployta.

## Päivitys

```
python -m scripts.update_international_results
git add data/international_results.csv
git commit -m "chore: refresh international_results snapshot"
```

martj42 päivittyy päivittäin; virkistä ennen turnausvaiheen deployta jotta tuoreimmat
ottelut ovat mukana.

## Skeema

`date, home_team, away_team, home_score, away_score, tournament, city, country, neutral`

- `home_score`/`away_score`: lopputulos jatkoajan jälkeen, **ilman rangaistuspotkuja**
  (shootout-tulokset erillisessä shootouts.csv:ssä, ei käytössä) → ei pakkais-inflaatiota (#70).
- `neutral`: TRUE/FALSE → venue-tieto (γ/2-neutralointi WC-otteluille).
- Tulevien ottelujen `home_score`/`away_score` = `NA` → loader suodattaa pois.

## Käyttö koodissa

`src/data/international_results.py` lukee tämän, suodattaa (pelatut + aikaikkuna +
48 WC-maata) ja palauttaa loaderin vakioskeeman + `tournament`/`neutral`-sarakkeet.
