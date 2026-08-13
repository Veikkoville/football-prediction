-- PUSH-NOTIF vaihe a: push_tokens-taulu + kirjoitus-RPC.
-- Spec: goaliq-app/cos-reports/push-notif-spec-2026-08-13.md
-- Villen GO 13.8.
--
-- ANON SALLITAAN TIETOISESTI: deadline-muistutus ei vaadi tilia, ja
-- kirjautumisen vaatiminen pushille karsisi juuri sen joukon jonka
-- retentio-ongelma koskee (appi avataan kerran eika palata). Premium-pushit
-- matchataan user_id -> profiles.is_premium, joten anon-token saa vain
-- ilmaisen deadline-kanavan.
--
-- Sama security-definer-kaava kuin set_fpl_prefs/set_fpl_draft: taululla EI
-- ole INSERT/UPDATE-policya millekaan roolille, vaan kaikki kirjoitus kulkee
-- RPC:n lapi. Backend lukee service-roolilla (ohittaa RLS:n).

create table if not exists public.push_tokens (
  -- Expon token on luonnollinen avain: sama laite = sama token, joten
  -- uudelleenrekisterointi paivittaa rivin eika luo duplikaattia.
  expo_token       text primary key,
  -- null = anon-laite. on delete set null, jotta tilin poisto ei tapa
  -- deadline-muistutusta laitteelta joka on yha kaytossa.
  user_id          uuid references auth.users(id) on delete set null,
  platform         text not null check (platform in ('ios', 'android')),
  -- KAIKKI OLETUKSENA POIS: store-review-riski ja spam-maine. Kayttaja
  -- kytkee itse, ja lokaali #44-notifi jaa fallbackiksi.
  opted_in_deadline boolean not null default false,
  opted_in_price    boolean not null default false,
  opted_in_picks    boolean not null default false,
  -- Quiet hours -laskentaan; null -> dispatch olettaa UTC+3 (RSL+EU-yleiso).
  locale           text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

comment on table public.push_tokens is
  'Expo push -tokenit. Kirjoitus vain upsert_push_token()/delete_push_token() kautta; backend lukee service-roolilla.';

-- Dispatch hakee kanavakohtaisesti -> osittaisindeksit pitavat kyselyn
-- kevyena kun tokeneita on paljon mutta opt-in on harvinaista.
create index if not exists push_tokens_deadline_idx
  on public.push_tokens (updated_at) where opted_in_deadline;
create index if not exists push_tokens_price_idx
  on public.push_tokens (user_id) where opted_in_price;
create index if not exists push_tokens_picks_idx
  on public.push_tokens (user_id) where opted_in_picks;

alter table public.push_tokens enable row level security;
-- Tarkoituksella EI policya: taulu on kirjoitettavissa vain RPC:lla ja
-- luettavissa vain service-roolilla. Tyhja policy-joukko = kaikki kielletty.

create or replace function public.push_token_is_valid(token text)
returns boolean
language sql
immutable
as $$
  -- Expon kaksi virallista muotoa. Muoto tarkistetaan jotta taulu ei tayty
  -- roskasta jos joku kutsuu RPC:ta suoraan; se EI ole turvatoimi vaan
  -- datan laadun vahti (aito esto on Expon oma toimitus).
  select token is not null
     and length(token) between 20 and 200
     and (token like 'ExponentPushToken[%]' or token like 'ExpoPushToken[%]');
$$;

create or replace function public.upsert_push_token(
  p_token    text,
  p_platform text,
  p_deadline boolean default false,
  p_price    boolean default false,
  p_picks    boolean default false,
  p_locale   text default null
)
returns timestamptz
language plpgsql
security definer
set search_path = public
as $$
declare
  ts timestamptz := now();
begin
  if not public.push_token_is_valid(p_token) then
    raise exception 'invalid expo push token';
  end if;
  if p_platform not in ('ios', 'android') then
    raise exception 'invalid platform';
  end if;

  insert into public.push_tokens as pt (
    expo_token, user_id, platform,
    opted_in_deadline, opted_in_price, opted_in_picks,
    locale, created_at, updated_at
  )
  values (
    p_token, auth.uid(), p_platform,
    coalesce(p_deadline, false), coalesce(p_price, false),
    coalesce(p_picks, false), p_locale, ts, ts
  )
  on conflict (expo_token) do update set
    -- Kirjautuminen laitteella, jolla token oli anon, SIIRTAA rivin tilille.
    -- Uloskirjautuminen EI nollaa user_id:ta (coalesce), jotta premium-pushit
    -- eivat katoa hetkellisen session paattymisen takia.
    user_id           = coalesce(auth.uid(), pt.user_id),
    platform          = excluded.platform,
    opted_in_deadline = excluded.opted_in_deadline,
    opted_in_price    = excluded.opted_in_price,
    opted_in_picks    = excluded.opted_in_picks,
    locale            = coalesce(excluded.locale, pt.locale),
    updated_at        = ts;

  return ts;
end;
$$;

create or replace function public.delete_push_token(p_token text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  -- Poisto ei vaadi omistajuutta: tokenin tietaminen tarkoittaa laitteen
  -- hallussapitoa, ja "lopeta pushit talta laitteelta" ei saa vaatia
  -- kirjautumista (anon-laite ei voisi koskaan lopettaa).
  delete from public.push_tokens where expo_token = p_token;
end;
$$;

revoke all on function public.upsert_push_token(text, text, boolean, boolean, boolean, text) from public;
revoke all on function public.delete_push_token(text) from public;
-- anon MUKANA tietoisesti: ks. otsikkokommentti.
grant execute on function public.upsert_push_token(text, text, boolean, boolean, boolean, text) to anon, authenticated;
grant execute on function public.delete_push_token(text) to anon, authenticated;

-- VERIFY (SQL-editorissa):
--   1) select upsert_push_token('ExponentPushToken[abcdefghijklmnop]', 'ios', true);
--        -> timestamptz; rivi taulussa, opted_in_deadline = true
--   2) select upsert_push_token('roska', 'ios');            -> exception
--   3) select upsert_push_token('ExponentPushToken[abcdefghijklmnop]', 'nokia'); -> exception
--   4) sama token uudelleen eri lipuilla                    -> 1 rivi, ei duplikaattia
--   5) select * from push_tokens;  (anon-roolilla)          -> 0 riviä (RLS)
--   6) select delete_push_token('ExponentPushToken[abcdefghijklmnop]'); -> rivi poistuu
