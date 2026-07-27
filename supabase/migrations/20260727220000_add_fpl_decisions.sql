-- FM-silmukka, vaihe A+B: päätöksen kirjaus + deadline-lukitus.
-- Määrittely: goaliq-app/cos-reports/team-manager-fm-loop-maarittely-2026-07-27.md
--
-- MIKSI TÄMÄ ON OLEMASSA
-- Nykyinen tuote on laskin: kysyt, se vastaa, poistut. Mikään ei muista mitä
-- viimeksi teit eikä kerro olitko oikeassa. Silmukka on:
--   malli sanoo -> sinä päätät -> deadline lukitsee -> kierros ratkeaa ->
--   silmukka kertoo kumpi oli oikeassa
-- Askel 5 on ainoa jota kilpailijoilla ei ole. Tämä taulu on askel 2 ja 3.
--
-- LUKITUS ON KOKO USKOTTAVUUDEN YDIN. Jälkikäteen muokattava päätös ei todista
-- mitään — se on sama periaate jolla mallin oma track record rakennettiin
-- (ennuste lokitetaan ENNEN ottelua, ks. data/prediction_log.json).
--
-- KIRJOITUSPOLKU: SECURITY DEFINER -funktio, sama syy kuin set_fpl_draft():ssa
-- (#66-kaava). Taululle EI anneta INSERT/UPDATE/DELETE-policyä authenticated-
-- roolille, jolloin ainoa reitti kantaan on funktio joka valvoo deadlinea.
-- Suora policy antaisi klientin kirjoittaa rivin milloin tahansa, myös
-- kierroksen ratkettua — ja silloin koko vertailu olisi arvoton.
--
-- Deploy: supabase db push TAI SQL-editor (🔒 GO-REQUIRED, prod-skeema).

create table if not exists public.fpl_decisions (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  gw            integer not null check (gw between 1 and 38),
  -- transfer | captain | chip | lineup
  kind          text not null check (kind in ('transfer','captain','chip','lineup')),
  -- Mallin suositus ja käyttäjän valinta SAMASSA muodossa, jotta ratkaisuvaihe
  -- voi laskea molemmat samalla koodilla. Vapaamuotoinen jsonb: sisältö riippuu
  -- kindistä (siirto = out/in-parit, kapteeni = pelaaja-id, jne).
  model_choice  jsonb not null,
  user_choice   jsonb not null,
  -- Seurasiko käyttäjä mallia. Johdettavissa vertaamalla, mutta tallennetaan
  -- eksplisiittisesti: vertailulogiikka voi muuttua, historian tulkinta ei saa.
  followed      boolean not null,
  -- GW:n virallinen deadline (FPL-datasta). Lukituksen raja.
  deadline_utc  timestamptz not null,
  -- PALVELINAIKA, ei klientin. Laitteen kello ei saa voida siirtää lukitusta.
  locked_at     timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  -- Yksi päätös per käyttäjä per GW per laji. Muokkaus on sallittu deadlineen
  -- asti (upsert), sen jälkeen ei.
  unique (user_id, gw, kind)
);

comment on table public.fpl_decisions is
  'FM-silmukka: käyttäjän päätös vs mallin suositus, lukittuna GW-deadlineen. Kirjoitus vain log_fpl_decision().';
comment on column public.fpl_decisions.locked_at is
  'Palvelinaika. Klientin kelloa ei käytetä: laitteen aika ei saa voida siirtää lukitusta.';

create index if not exists fpl_decisions_user_gw_idx
  on public.fpl_decisions (user_id, gw);

alter table public.fpl_decisions enable row level security;

-- LUKU: vain oma historia. Kausihistoria on premium-ominaisuus, mutta gate on
-- SOVELLUKSESSA eikä täällä: kanta ei tiedä tilaustilaa, ja RLS:n tehtävä on
-- eristää käyttäjät toisistaan — ei myydä.
drop policy if exists "own decisions readable" on public.fpl_decisions;
create policy "own decisions readable"
  on public.fpl_decisions for select
  using (auth.uid() = user_id);

-- EI INSERT/UPDATE/DELETE-policyä. Tarkoituksellisesti: ainoa kirjoitusreitti
-- on log_fpl_decision(), joka valvoo deadlinea. Ks. tiedoston otsikko.

-- ---------------------------------------------------------------------------
-- Kirjoitusfunktio
-- ---------------------------------------------------------------------------
create or replace function public.log_fpl_decision(
  p_gw           integer,
  p_kind         text,
  p_model_choice jsonb,
  p_user_choice  jsonb,
  p_followed     boolean,
  p_deadline_utc timestamptz
)
returns timestamptz
language plpgsql
security definer
set search_path = public
as $$
declare
  ts timestamptz := now();
  existing_deadline timestamptz;
begin
  if auth.uid() is null then
    raise exception 'not authenticated';
  end if;
  if p_kind not in ('transfer','captain','chip','lineup') then
    raise exception 'invalid kind: %', p_kind;
  end if;
  if p_gw is null or p_gw < 1 or p_gw > 38 then
    raise exception 'invalid gw: %', p_gw;
  end if;

  -- LUKITUS. Deadline tulee klientiltä (se on FPL-datassa, ei kannassa), mutta
  -- kaksi vartijaa tekee siitä kelvollisen:
  --   1) uutta riviä ei voi kirjata deadlinen jälkeen
  --   2) OLEMASSA OLEVAN rivin deadlinea ei voi siirtää eteenpäin
  -- Ilman (2) klientti voisi kirjata deadlinen ensin oikein ja "korjata" sitä
  -- myöhemmin nähtyään tuloksen. locked_at on palvelinaikaa, joten
  -- ratkaisuvaihe voi lisäksi ristiintarkistaa sen oikeaa FPL-deadlinea vasten.
  if ts >= p_deadline_utc then
    raise exception 'gameweek % is locked (deadline %)', p_gw, p_deadline_utc;
  end if;

  select deadline_utc into existing_deadline
    from public.fpl_decisions
   where user_id = auth.uid() and gw = p_gw and kind = p_kind;

  if existing_deadline is not null and p_deadline_utc > existing_deadline then
    raise exception 'deadline cannot move forward (was %, got %)',
      existing_deadline, p_deadline_utc;
  end if;

  insert into public.fpl_decisions
      (user_id, gw, kind, model_choice, user_choice, followed, deadline_utc,
       locked_at, updated_at)
  values
      (auth.uid(), p_gw, p_kind, p_model_choice, p_user_choice, p_followed,
       p_deadline_utc, ts, ts)
  on conflict (user_id, gw, kind) do update
     set model_choice = excluded.model_choice,
         user_choice  = excluded.user_choice,
         followed     = excluded.followed,
         updated_at   = ts;
         -- locked_at ja deadline_utc EIVÄT päivity: ensimmäinen lukitus jää
         -- voimaan, muuten "lukittu ennen deadlinea" ei tarkoittaisi mitään.

  return ts;
end;
$$;

revoke all on function public.log_fpl_decision(integer, text, jsonb, jsonb, boolean, timestamptz) from public;
revoke all on function public.log_fpl_decision(integer, text, jsonb, jsonb, boolean, timestamptz) from anon;
grant execute on function public.log_fpl_decision(integer, text, jsonb, jsonb, boolean, timestamptz) to authenticated;

grant select on public.fpl_decisions to authenticated;

-- VERIFY (aja SQL-editorissa migraation jälkeen):
--   1) Taulu + RLS:
--      select relrowsecurity from pg_class where relname = 'fpl_decisions';  -- t
--   2) Kirjoitus kirjautuneena (deadline tulevaisuudessa):
--      supabase.rpc('log_fpl_decision', {p_gw:1, p_kind:'captain',
--        p_model_choice:{id:1}, p_user_choice:{id:2}, p_followed:false,
--        p_deadline_utc:'2026-08-21T17:30:00Z'})   -> timestamptz
--   3) Lukitus pitää:
--      sama kutsu p_deadline_utc:'2020-01-01T00:00:00Z'  -> exception 'is locked'
--   4) Deadlinea ei voi siirtää eteenpäin:
--      kirjaa GW1 deadlinella X, sitten sama X+1 vrk       -> exception
--   5) Eristys: tili A ei näe tili B:n rivejä (select palauttaa vain omat);
--      anon ei voi kutsua funktiota eikä lukea taulua.
--   6) Suora kirjoitus on estetty:
--      supabase.from('fpl_decisions').insert({...})        -> RLS-virhe
