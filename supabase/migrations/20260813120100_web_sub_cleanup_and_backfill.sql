-- WEB-SUB-SYNC (13.8.2026), osa 2/2: kertaluonteinen siivous + backfill.
-- Idempotentti: WHERE-ehdot no-opaavat uusinta-ajossa.

-- 1. Testitilin haamurivit: Stripen totuus (read-only-avain 12.8) =
--    aktiivisia tilauksia tasan 2; kannan 4 "active"-rivista ylimaaraiset
--    ovat example.com-testitilin 5.7 luomia (season 2027-06-30 -fallback +
--    monthly jonka kausi paattyi 5.8 mutta status jai "active").
UPDATE public.web_subscriptions ws
SET status = 'cancelled'
FROM auth.users u
WHERE u.id = ws.user_id
  AND u.email LIKE '%@example.com'
  AND ws.status = 'active';

-- 2. Testitilin profiili alas samalla.
UPDATE public.profiles p
SET is_premium = false,
    subscription_current_period_end = NULL
FROM auth.users u
WHERE u.id = p.id
  AND u.email LIKE '%@example.com'
  AND p.is_premium;

-- 3. premium_source-backfill, jarjestys tarkoituksellinen:
--    ensin stripe_web (kova evidenssi = aktiivinen web-tilausrivi,
--    ajetaan siivouksen JALKEEN jottei testitili saa leimaa) ...
UPDATE public.profiles p
SET premium_source = 'stripe_web'
WHERE p.is_premium
  AND p.premium_source IS NULL
  AND p.id IN (SELECT user_id FROM public.web_subscriptions
               WHERE status = 'active');

--    ... sitten LOPUT premium-tilit = comp. Kaksi aitoa RevenueCat-
--    tilaajaa saavat vaaran 'comp'-leiman korkeintaan yhdeksi
--    laskutusjaksoksi: RC:n seuraava RENEWAL-webhook kirjoittaa
--    'revenuecat' paalle automaattisesti (fp 92f0c028). Itsekorjautuva.
UPDATE public.profiles
SET premium_source = 'comp'
WHERE is_premium AND premium_source IS NULL;
