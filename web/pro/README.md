# GoalIQ Pro — FPL-dashboard (pro.goaliq.app)

Kevyt Streamlit-appi joka lukee GoalIQ:n LIVE-API:a (`/api/fantasy` free,
`/api/fantasy/xp` premium). **Ei mallikoodia** — vain HTTP-JSON + auth + billing.
Erillinen tuote: EI liity vanhaan vville-football-Streamlitiin (betting, parkissa).

## Rakenne

| Tiedosto | Rooli |
|---|---|
| `app.py` | Päänäkymä: free (CS%+FDR+track record) + Pro (xP-lista, kapteeni-ranker) + paywall |
| `auth.py` | Supabase-login (sama tili kuin mobiilissa) + `web_subscriptions`-status |
| `billing.py` | Stripe Checkout (kausi 25 €/vuosi [recurring, UI-oletus] + 3,99 €/kk — MOLEMMAT subscriptioneita) + success-redirect-verify |
| `data.py` | API-fetchit + cache (15 min) |
| `sql/web_subscriptions.sql` | Supabase-taulu + RLS (aja SQL-editorissa) |
| `.env.example` | Kaikki tarvittavat secretit dokumentoituna |

Tilauksen aktivointi on kaksipolkuinen ja idempotentti:
1. **Webhook (tuotanto-ensisijainen):** Stripe → backend `POST /api/webhook/stripe-web`
   (api/main.py) → upsert `web_subscriptions`. Vaatii Render-envit:
   `STRIPE_WEB_WEBHOOK_SECRET` (uusi) + `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` (on jo).
2. **Success-redirect-verify (fallback + test-mode):** `?session_id=...` →
   appi verifioi Stripe-API:sta → upsert. Toimii ilman deployattua webhookkia.

## Villen setup ennen test-modea (~15 min)

1. **Supabase** (sama projekti): aja `sql/web_subscriptions.sql` SQL-editorissa.
2. **Stripe (test-mode):** ✅ TEHTY (CoS 5.7) — tuote "GoalIQ Pro (web)" + 2
   recurring-hintaa (25 €/vuosi + 3,99 €/kk), id:t `STRIPE_SUPABASE_CONFIG.md`:ssä.
3. **Secretit:** kopioi `.env.example` → täytä (test-avaimet!) → lokaalisti
   `.env`/ympäristö TAI hostin secret-dashboard.
4. **Aja:** `pip install -r web/pro/requirements.txt` →
   `streamlit run web/pro/app.py` → e2e: luo tili → Season pass →
   Stripe-testikortti `4242 4242 4242 4242` → redirect → "Premium active" →
   xP-näkymät aukeavat.

## 🔒 GO-REQUIRED ennen liveä (EI ilman Villen lupaa)

- Stripe LIVE-avaimet + live-hinnat (test → live -vaihto).
- Backend-deploy (webhook-endpoint on koodissa, EI vielä pushattu Renderiin)
  + Render-env `STRIPE_WEB_WEBHOOK_SECRET` + Stripe-dashboardiin webhook-endpoint
  `https://goaliq-api.onrender.com/api/webhook/stripe-web`
  (eventit: checkout.session.completed, customer.subscription.updated/deleted).
- Hostaus: **Streamlit Community Cloud** (ilmainen; repo+branch+file `web/pro/app.py`,
  secrets dashboardiin) TAI **Render** (uusi service). Custom domain
  `pro.goaliq.app` = Cloudflare CNAME → hostin osoite.
- `APP_BASE_URL=https://pro.goaliq.app` kun domain live.
- goaliq.app/fpl.html:ään linkki pro:hon (free-funneli) — erillinen pikkucommit.

## Tunnetut rajaukset (v1)

- `/api/fantasy/xp` on julkinen endpoint → paywall on UI-tasolla (sama malli
  kuin mobiilissa). Token-gating = Phase 2 jos tarpeen.
- Differential-näkymä (xP vs omistus-%) = Phase 2 (vaatii FPL-omistusdatan,
  saatavilla vasta kun 26/27-peli aukeaa).
- Komponenttierittely (maalit/CS/defcon) renderöityy kun backend tuo kentät
  xP-JSONiin (QUEUE #3 backend-osa).
- GDPR: auth = henkilödata → footer linkittää goaliq.app/privacy.html:ään;
  privacy-tekstiin web-maininta ennen liveä (CoS).
