# GoalIQ Pro — Render-deploy (turnkey, QUEUE #9)

Ville tekee kohdat joissa 🔒 (secretit/GO). Kaikki muu on valmiina repossa.

## 1. Render Web Service (käsin, sama tapa kuin goaliq-api)

Render-dashboard → New → Web Service → repo `Veikkoville/football-prediction`, branch `main`:

| Asetus | Arvo |
|---|---|
| Name | `goaliq-pro-web` |
| Region | Frankfurt |
| Runtime | Python |
| Build Command | `pip install -r web/pro/requirements.txt` |
| Start Command | `streamlit run web/pro/app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true --server.fileWatcherType none --browser.gatherUsageStats false` |
| Health Check Path | `/_stcore/health` |
| Plan | Free (starter jos cold-start haittaa maksavia) |
| Environment Variable | `PYTHON_VERSION` = `3.11` |

(Sama määrittely on myös root-`render.yaml`:issa `goaliq-pro-web`-entrynä dokumentaationa.)

## 2. 🔒 Env-varit goaliq-pro-web-serviceen (LIVE-arvot)

| Env | Arvo | Mistä |
|---|---|---|
| `SUPABASE_URL` | `https://bhcgommvjlhqcktrbtxf.supabase.co` | sama kuin nyt |
| `SUPABASE_ANON_KEY` | (sama kuin mobiilissa) | Supabase → Project Settings → API |
| `SUPABASE_SERVICE_ROLE_KEY` | (sama kuin API-servicellä) | Supabase → Project Settings → API |
| `STRIPE_SECRET_KEY` | **sk_live_…** | Stripe → Developers → API keys (LIVE) |
| `STRIPE_PRICE_MONTHLY_ID` | `price_1TptoiFLROrR5x8wBmeFiizv` | LIVE-hinta (CoS loi 5.7) |
| `STRIPE_PRICE_SEASON_ID` | `price_1TptqDFLROrR5x8wQvsKpCMy` | LIVE-hinta (CoS loi 5.7) |
| `APP_BASE_URL` | `https://pro.goaliq.app` | (Checkout-redirectit) |

## 3. 🔒 Env-vari OLEMASSA OLEVAAN goaliq-api-serviceen

| Env | Arvo | Mistä |
|---|---|---|
| `STRIPE_WEB_WEBHOOK_SECRET` | **whsec_…** | tulee kohdan 5c webhook-rekisteröinnistä |

(SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY ovat API-servicellä jo.)

## 4. Huomiot

- Streamlit toimii Renderissä websocketeilla suoraan (ei erillisiä proxy-asetuksia).
- Free-tier nukkuu 15 min idlen jälkeen → 1. avaus ~30 s. Maksavalle tuotteelle
  harkitse starter-plania ($7/kk) kun ensimmäiset tilaukset tulevat.
- `web/pro/.env` on vain lokaaliin test-modeen (gitignored) — hostissa
  Render-envit; `envload.py` on hostissa no-op.

## 5. 🔒 GO-LIVE-SEKVENSSI (järjestyksessä; a = Villen push-GO)

a) **`git push origin main`** (GO-nippu: web-v1-commitit) → goaliq-api
   redeployautuu → webhook-endpoint `/api/webhook/stripe-web` live
   (palauttaa "not configured" -warningin kunnes 5c+3 tehty = turvallinen).
b) **Luo goaliq-pro-web-service** (kohta 1) + envit (kohta 2) → service
   käynnistyy → verify `https://goaliq-pro-web.onrender.com/_stcore/health` = ok
   ja sivu renderöityy.
c) **Stripe LIVE-webhook:** Stripe Dashboard (LIVE-mode) → Developers →
   Webhooks → Add endpoint `https://goaliq-api.onrender.com/api/webhook/stripe-web`,
   eventit: `checkout.session.completed`, `customer.subscription.updated`,
   `customer.subscription.deleted` → kopioi **whsec_** → API-servicen env
   (kohta 3) → manual redeploy API:lle (env-muutos).
d) **DNS:** Cloudflare → `pro.goaliq.app` CNAME → goaliq-pro-web-servicen
   onrender.com-osoite (DNS only) + Render-serviceen Custom Domain
   `pro.goaliq.app` (Render hoitaa sertin). (CoS voi tehdä selaimessa.)
e) **Live-smoke:** pro.goaliq.app aukeaa (free-taulut + track record) →
   luo tili → PIENIN oikea testi harkiten TAI Stripe-testikellon sijaan
   luota test-mode-e2e:hen (jo ajettu) + tarkista webhook-delivery Stripestä
   ensimmäisen oikean oston yhteydessä. `fpl.html`:ään linkki pro:hon
   (erillinen pikkucommit go-liven jälkeen).
