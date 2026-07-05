# Web-v1 Stripe + Supabase -config (tila 5.7.2026)

CoS teki selaimessa Villen pyynnöstä. Test-mode. Live = GO-REQUIRED.

## ✅ CoS teki (Stripe TEST, tili `acct_1TUSSEFLROrR5x8w`)

Luotu tuote **"GoalIQ Pro (web)"** + 2 recurring-hintaa (molemmat subscription):

| Env-muuttuja | Arvo | Hinta |
|---|---|---|
| (product) | `prod_UpVi544kZfMly4` | GoalIQ Pro (web) |
| `STRIPE_PRICE_MONTHLY_ID` | `price_1TpqhGFLROrR5x8wOQZlnqWk` | 3,99 €/kk (Monthly, recurring) |
| `STRIPE_PRICE_SEASON_ID` | `price_1Tpqm2FLROrR5x8wZLBZJtbo` | 25 €/vuosi (Yearly, recurring) |

(Hinta-ID:t + product-ID EIVÄT ole salaisia → turvallista käyttää `.env`:issä.)

## ⚠️ KOODIHUOMIO CC:lle (pakko ennen e2e-testiä)

README/scaffold oletti **kausi = one-time** (`STRIPE_PRICE_SEASON_ID` one-time). **Villen päätös = 25 €/vuosi VUOSITTAIN UUSIUTUVA** → hinta luotu recurring-yearlyna. **`web/pro/billing.py`: varmista että Stripe Checkout käyttää `mode='subscription'` MOLEMMILLE hinnoille** (ei `mode='payment'` kaudelle). Success-verify + webhook käsittelevät molemmat subscriptioneina. Pieni tweak jos oletti one-timen.

## 🔒 Villen jäljellä (secretit — CoS EI voi käsitellä)

1. ✅ **Supabase SQL AJETTU 5.7** (Ville liitti + Run, "Success. No rows returned" → `web_subscriptions`-taulu + trigger + RLS + "own subscription read" -policy luotu). CoS-automaatio ei taipunut (editorin auto-close + laajennuksen ctrl+v ei injektoinut leikepöytää + Supabase-häiriö) → tehtiin CoS-ohjatulla Villen Ctrl+V:llä.
2. **Secretit `.env`:iin / hostin secret-manageriin** (test-avaimet):
   - `STRIPE_SECRET_KEY` = sk_test_… (Stripe → Developers → API keys)
   - `STRIPE_PUBLISHABLE_KEY` = pk_test_51TUSSEFLROrR5x8w… (sama sivu)
   - `STRIPE_PRICE_MONTHLY_ID` / `STRIPE_PRICE_SEASON_ID` = yllä
   - `SUPABASE_URL` = https://bhcgommvjlhqcktrbtxf.supabase.co
   - `SUPABASE_ANON_KEY` + `SUPABASE_SERVICE_ROLE_KEY` (Supabase → Project Settings → API)
3. **Lokaali e2e (CC/terminaali):** `pip install -r web/pro/requirements.txt` → `streamlit run web/pro/app.py` → luo tili → Season pass → testikortti 4242 4242 4242 4242 → "Premium active" → xP aukeaa.

## ✅ STRIPE LIVE -HINNAT LUOTU 5.7 (CoS, selain) — GO-liveä varten

Live-tuote **"GoalIQ Pro (web)"** + 2 recurring-hintaa (LIVE-mode). Nämä LIVE-price-id:t menevät **hostin (Render) live-env:iin**, EI lokaaliin test-`.env`:iin:

| Env-muuttuja (LIVE) | Arvo | Hinta |
|---|---|---|
| (product) | `prod_UpYw5IUJddKOXm` | GoalIQ Pro (web) LIVE |
| `STRIPE_PRICE_MONTHLY_ID` | `price_1TptoiFLROrR5x8wBmeFiizv` | 3,99 €/kk LIVE |
| `STRIPE_PRICE_SEASON_ID` | `price_1TptqDFLROrR5x8wQvsKpCMy` | 25 €/vuosi LIVE |

Live-avaimet (`sk_live_`, webhook `whsec_`) = Villen kättä, hostin secreteihin GO-liveessä.

## 🔒 GO-REQUIRED (ei ilman Villen lupaa)
- Webhook Stripe-dashboardiin `https://goaliq-api.onrender.com/api/webhook/stripe-web` + Render-env `STRIPE_WEB_WEBHOOK_SECRET` (backend-deploy).
- Live-avaimet + live-hinnat (test → live).
- Host (Streamlit Cloud / Render) + `pro.goaliq.app`-DNS (Cloudflare CNAME = CoS).
