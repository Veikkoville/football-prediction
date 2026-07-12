-- #66 VAIHE 2: FPL entry-ID tili-tasolle (cross-device).
--
-- profiles.fpl_entry_id = kayttajan JULKINEN FPL entry-ID (sama numero URL:ssa
-- fantasy.premierleague.com/entry/<id>/...). Ei salasana, ei arkaluontoinen.
-- Pysyva yli kausien -> kertatallennus kantaa.
--
-- KIRJOITUSPOLKU (turvallisin vaihtoehto, perustelu):
--   profiles-taulussa EI ole UPDATE-policya authenticated-roolille (is_premium
--   kirjoitetaan VAIN service-roolilla: RevenueCat-webhook + Stripe-webhook,
--   NO-CLOBBER-guardit). Rivi-tason UPDATE-policyn lisaaminen avaisi KAIKKI
--   sarakkeet omalle riville (RLS on rivi- ei saraketasoinen) -> kayttaja
--   voisi kirjoittaa oman is_premium=true. Siksi kirjoitus kulkee SECURITY
--   DEFINER -funktion kautta, joka paivittaa VAIN fpl_entry_id-sarakkeen ja
--   VAIN auth.uid():n omalle riville. Ei muutoksia olemassa oleviin
--   policyihin/grantteihin -> is_premium-polku koskematon.
--
-- LUKUPOLKU: olemassa oleva "oma rivi" -SELECT-policy kattaa uuden sarakkeen
-- (mobiili tekee jo select * ja web select is_premium omalta rivilta).
--
-- Deploy: supabase db push TAI SQL-editor (GO-REQUIRED, prod-skeema).

alter table public.profiles
  add column if not exists fpl_entry_id bigint
  check (fpl_entry_id is null or (fpl_entry_id > 0 and fpl_entry_id < 10000000000));

comment on column public.profiles.fpl_entry_id is
  '#66: julkinen FPL entry-ID (cross-device personointi). Kirjoitus vain set_fpl_entry_id()-funktiolla.';

-- Kirjoitusfunktio: paivittaa vain oman rivin fpl_entry_id:n. NULL = forget.
-- Sarakkeen CHECK validoi arvoalueen. Jos profiilirivia ei ole (ei pitaisi
-- tapahtua - signup-trigger luo sen), update on no-op (fail-safe).
create or replace function public.set_fpl_entry_id(entry bigint)
returns void
language sql
security definer
set search_path = public
as $$
  update public.profiles
     set fpl_entry_id = entry
   where id = auth.uid();
$$;

revoke all on function public.set_fpl_entry_id(bigint) from public;
revoke all on function public.set_fpl_entry_id(bigint) from anon;
grant execute on function public.set_fpl_entry_id(bigint) to authenticated;

-- VERIFY (aja SQL-editorissa migraation jalkeen):
--   1) Sarake + constraint:
--      select column_name, data_type from information_schema.columns
--       where table_name = 'profiles' and column_name = 'fpl_entry_id';
--   2) RLS-eristys (user A ei nae/kirjoita user B:n rivia):
--      - kirjaudu clientilla tilina A -> supabase.rpc('set_fpl_entry_id', {entry: 1578623})
--      - select fpl_entry_id from profiles -> A nakee VAIN oman rivinsa (SELECT-policy)
--      - tilin B rivi ei muutu (funktio paivittaa vain auth.uid():n rivin)
--   3) anon ei voi kutsua funktiota (revoke) eika auth.uid() osu riviin.
