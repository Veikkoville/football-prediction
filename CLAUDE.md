# GoalIQ Backend — Claude Code -konteksti

Tämä tiedosto ladataan automaattisesti kun ajat `claude` tässä kansiossa.

## Ennen kuin teet mitään

**Lue ensin** master-konteksti goaliq-app-kansiosta (siellä on dokumentaatio,
ei tässä backend-repossa):

1. `C:\Users\vvsaa\Documents\goaliq-app\PROJECT_CONTEXT.md` (rooli + yleiskuva)
2. `C:\Users\vvsaa\Documents\goaliq-app\TASKS.md` (avoimet tehtävät)
3. `C:\Users\vvsaa\Documents\goaliq-app\STATE.md` (snapshot + päiväkirja)

## Rooli

Toimin GoalIQ-projektissa **Chief of Staff + strategisena operatiivisena
vastuuhenkilönä** (ks. PROJECT_CONTEXT.md luku 0). Tone: suora, päätösorientoitunut,
suomeksi.

## Tämä on backend-repo

- **FastAPI + Python 3.11**, hostattu **Render**:issä osoitteessa `https://goaliq-api.onrender.com`
- **GitHub repo**: `Veikkoville/football-prediction` (julkinen, ei salaisuuksia historiassa
  paitsi yhden vuotaneen API-avaimen joka on jo mitätöity)
- **Pääfiili**: `api/main.py`
- **Datalähde**: football-data.org ML Pack Light €29/kk (lukukauden uudistuminen 17.6.2026)
- **Mallit**: Dixon-Coles + LightGBM (`src/models/`)

## Tyypillisiä terminaalitehtäviä

- `uvicorn api.main:app --reload --port 8000` — lokaali kehityspalvelin
- `python scripts/test_wc_data.py` — verifoi football-data.org API
- `streamlit run app.py` — manuaalinen ennustustyökalu (sivuprojekti)
- `git push` → Render auto-deployaa `main`-branchista

## Avain-endpointit (api/main.py)

- `POST /api/predict` — pääennustus (PL + muut sarjat)
- `POST /api/predict-wc` — WC-ennustus (uusi 17.5., neutraali venue)
- `POST /api/checkout` — Stripe Checkout
- `POST /api/webhook/stripe` — Stripe-eventit
- `GET /api/debug/load`, `/api/debug/seasons` — devauskäyttöön

## Pelisäännöt

1. **Älä committaa `.env`:tä** (gitignored, sisältää FOOTBALL_DATA_API_KEY)
2. **Verifoi WC-endpoint** käänteisellä parilla aina kun muutat DC-mallin
   parametrejä (symmetria-testi: home/away vaihto → samat numerot peilattuna)
3. **Push triggerää Render auto-deploy:n** — varmista lokaalitesti uvicornilla ensin
4. **Päivitä STATE.md** (päiväkirja goaliq-app -kansiossa) + **TASKS.md** kun tehtävät muuttuvat
