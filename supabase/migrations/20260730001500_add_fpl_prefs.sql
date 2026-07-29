-- Beat the model V3 (watchlist) + V4 (kauden tavoite): profiles.fpl_prefs.
-- Määrittely: goaliq-app/cos-reports/beat-the-model-maarittely-2026-07-29.md
-- Villen GO 29.7 ("myllytä noi football manager ideoinnit kaikki läpi").
--
-- Yksi jsonb-sarake kahdelle kevyelle preferenssille, koska kumpikaan ei
-- tarvitse rivitason kyselyjä: watchlist luetaan aina kokonaisena ja tavoite
-- on yksi arvo. Sama security-definer-kaava kuin fpl_draft (profiles-taulussa
-- ei ole UPDATE-policyä authenticated-roolille — policy avaisi myös
-- is_premium-sarakkeen).
--
-- Muoto: {"v":1,"watchlist":[int,...],"objective":{"kind":"overall_rank",
--         "value":int}|null,"updated_at":"ISO"}
--
-- Deploy: supabase db push (🔒 GO annettu 29.7).

alter table public.profiles
  add column if not exists fpl_prefs jsonb;

comment on column public.profiles.fpl_prefs is
  'FPL-preferenssit (watchlist + kauden tavoite), cross-device. Kirjoitus vain set_fpl_prefs().';

create or replace function public.fpl_prefs_is_valid(prefs jsonb)
returns boolean
language sql
immutable
as $$
  select prefs is null or (
    jsonb_typeof(prefs) = 'object'
    -- watchlist: puuttuva kelpaa; annettu = max 50 positiivista kokonaislukua.
    -- 50 on tarkoituksella reilusti yli premium-käytön — raja on roskadatan
    -- torjuntaa, ei tuotegate (gate on sovelluksessa: free 3, premium rajatta).
    and (
      prefs -> 'watchlist' is null
      or (
        jsonb_typeof(prefs -> 'watchlist') = 'array'
        and jsonb_array_length(prefs -> 'watchlist') <= 50
        and not exists (
          select 1
            from jsonb_array_elements(prefs -> 'watchlist') as e
           where jsonb_typeof(e) <> 'number'
              or (e)::numeric <= 0
              or (e)::numeric <> trunc((e)::numeric)
        )
      )
    )
    -- objective: puuttuva/null kelpaa; annettu = {kind:'overall_rank', value>0}.
    -- kind on suljettu lista jotta uudet tavoitetyypit vaativat migraation
    -- (= tietoisen päätöksen), eivät vain klienttimuutosta.
    and (
      prefs -> 'objective' is null
      or jsonb_typeof(prefs -> 'objective') = 'null'
      or (
        jsonb_typeof(prefs -> 'objective') = 'object'
        and prefs -> 'objective' ->> 'kind' in ('overall_rank')
        and jsonb_typeof(prefs -> 'objective' -> 'value') = 'number'
        and (prefs -> 'objective' ->> 'value')::numeric > 0
        and (prefs -> 'objective' ->> 'value')::numeric
            = trunc((prefs -> 'objective' ->> 'value')::numeric)
      )
    )
  );
$$;

alter table public.profiles
  drop constraint if exists profiles_fpl_prefs_shape;
alter table public.profiles
  add constraint profiles_fpl_prefs_shape
  check (public.fpl_prefs_is_valid(fpl_prefs)) not valid;

create or replace function public.set_fpl_prefs(prefs jsonb)
returns timestamptz
language plpgsql
security definer
set search_path = public
as $$
declare
  stamped jsonb;
  ts timestamptz := now();
begin
  if prefs is null then
    update public.profiles set fpl_prefs = null where id = auth.uid();
    return ts;
  end if;

  if not public.fpl_prefs_is_valid(prefs) then
    raise exception 'invalid fpl_prefs shape';
  end if;

  stamped := jsonb_build_object(
    'v', 1,
    'updated_at', to_char(ts at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
  );
  if prefs -> 'watchlist' is not null then
    stamped := stamped || jsonb_build_object('watchlist', prefs -> 'watchlist');
  end if;
  if prefs -> 'objective' is not null
     and jsonb_typeof(prefs -> 'objective') = 'object' then
    stamped := stamped || jsonb_build_object('objective', prefs -> 'objective');
  end if;

  update public.profiles set fpl_prefs = stamped where id = auth.uid();
  return ts;
end;
$$;

revoke all on function public.set_fpl_prefs(jsonb) from public;
revoke all on function public.set_fpl_prefs(jsonb) from anon;
grant execute on function public.set_fpl_prefs(jsonb) to authenticated;

-- VERIFY (SQL-editorissa):
--   1) set_fpl_prefs({watchlist:[1,2,3]})                          -> ok
--   2) set_fpl_prefs({watchlist:['x']})                            -> exception
--   3) set_fpl_prefs({objective:{kind:'overall_rank',value:1000000}}) -> ok
--   4) set_fpl_prefs({objective:{kind:'mini_league',value:1}})     -> exception
--   5) select fpl_prefs from profiles;  -- stamped v/updated_at mukana
