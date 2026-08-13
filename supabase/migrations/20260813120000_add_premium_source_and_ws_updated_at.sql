-- WEB-SUB-SYNC (13.8.2026), osa 1/2: skeema.
-- Tausta: web_subscriptions ei koskaan paivittynyt luonnin jalkeen
-- (dashboardin webhook-tilauksesta puuttuivat subscription-eventit) eika
-- premium-tileista voinut erottaa lahdetta (stripe_web/revenuecat/comp).
-- Koodipuoli: api/main.py _stamp_premium_source (fp 92f0c028).

-- 1. premium_source: koodi leimaa stripe_web/revenuecat automaattisesti,
--    comp asetetaan VAIN kasin/SQL:lla (koodipolkua ei ole tarkoituksella).
ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS premium_source text
  CHECK (premium_source IN ('stripe_web', 'revenuecat', 'comp')
         OR premium_source IS NULL);

-- 2. web_subscriptions.updated_at liikkuu jatkossa itsestaan. Ilman tata
--    sync toimii mutta updated_at jaa jumiin eika "milloin rivi viimeksi
--    paivittyi" -audit ole koskaan luotettava (12.8 diagnoosi nojasi
--    juuri tahan kenttaan).
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS web_subscriptions_set_updated_at ON public.web_subscriptions;
CREATE TRIGGER web_subscriptions_set_updated_at
  BEFORE UPDATE ON public.web_subscriptions
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
