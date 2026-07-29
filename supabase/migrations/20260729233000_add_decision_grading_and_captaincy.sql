-- Beat the model V1 (grading) + kapteeni/vice draftiin (K3-niputus).
-- Määrittely: goaliq-app/cos-reports/beat-the-model-maarittely-2026-07-29.md
-- Villen GO 29.7.2026 (K3: molemmat samaan migraatioon).
--
-- OSA A — fpl_decisions saa grading-kentät.
--
-- Gradaus on BACKEND-ERÄAJO service-roolilla (API:n grade-endpoint, sama
-- ADMIN_TOKEN-kaava kuin clear-cache). Klientti ei koskaan gradaa itseään —
-- sama periaate kuin lukituksessa. Service-rooli ohittaa RLS:n, joten uusia
-- policyjä ei tarvita; klientti lukee graded-kentät olemassa olevalla
-- "own decisions readable" -policyllä.
--
-- IMMUTABILITY on rehellisyysportti, ei mukavuus: gradattu rivi on sama
-- lupaus kuin lokitettu ennuste. Trigger estää gradattujen kenttien
-- muuttamisen MYÖS service-roolilta (RLS ei koske service-roolia, trigger
-- koskee). Ainoa polku on NULL -> arvo, ei koskaan arvo -> toinen arvo.
--
-- Deploy: supabase db push TAI SQL-editor (🔒 GO annettu 29.7).

alter table public.fpl_decisions
  add column if not exists graded_at    timestamptz,
  add column if not exists model_points numeric,
  add column if not exists user_points  numeric,
  add column if not exists grade_note   text;

comment on column public.fpl_decisions.graded_at is
  'Milloin backend-grader ratkaisi rivin. NULL = ei vielä gradattu. Immutable trigger-vartioinnilla.';
comment on column public.fpl_decisions.model_points is
  'Mallin valinnan toteutuneet FPL-pisteet (kapteeni: pisteet x2; siirto: in - out).';
comment on column public.fpl_decisions.user_points is
  'Käyttäjän valinnan toteutuneet pisteet samalla kaavalla. NULL = ei gradattavissa (ks. grade_note).';
comment on column public.fpl_decisions.grade_note is
  'Koneluettava syy: ok | no_entry_id | picks_unavailable | player_missing | kind_not_graded.';

create or replace function public.fpl_decisions_guard_grading()
returns trigger
language plpgsql
as $$
begin
  -- Gradattu rivi on immutable gradauksen osalta: kerran kirjoitettu tulos ei
  -- muutu, ei edes service-roolilta. (Päätöskentät suojaa log_fpl_decision,
  -- joka ei päivitä deadlinen jälkeen; tämä vartioi tuloskenttiä.)
  if old.graded_at is not null and (
       new.graded_at    is distinct from old.graded_at
    or new.model_points is distinct from old.model_points
    or new.user_points  is distinct from old.user_points
    or new.grade_note   is distinct from old.grade_note
  ) then
    raise exception 'graded decision is immutable (graded_at %)', old.graded_at;
  end if;
  -- Gradaus vasta deadlinen jälkeen: ennen sitä tulosta ei ole olemassa.
  if new.graded_at is not null and old.graded_at is null
     and new.graded_at < old.deadline_utc then
    raise exception 'cannot grade before deadline (%)', old.deadline_utc;
  end if;
  return new;
end;
$$;

drop trigger if exists fpl_decisions_guard_grading on public.fpl_decisions;
create trigger fpl_decisions_guard_grading
  before update on public.fpl_decisions
  for each row execute function public.fpl_decisions_guard_grading();

-- Grader hakee gradaamattomat tehokkaasti.
create index if not exists fpl_decisions_ungraded_idx
  on public.fpl_decisions (gw) where graded_at is null;

-- ---------------------------------------------------------------------------
-- OSA B — kapteeni/vice fpl_draft-jsoniin (K3-niputus, sama migraatiokierros).
--
-- Muoto laajenee: {"v":1,"ids":[...],"captain_id":N,"vice_id":M,"updated_at":...}
-- captain_id/vice_id ovat valinnaisia; kun molemmat annetaan, niiden pitää
-- erota toisistaan ja kuulua ids-listaan. Validointi kannassa asti samasta
-- syystä kuin ids-listalla: rikkinäinen klientti ei saa täyttää saraketta
-- mielivaltaisella JSONilla.
-- ---------------------------------------------------------------------------

create or replace function public.fpl_draft_is_valid(draft jsonb)
returns boolean
language sql
immutable
as $$
  select draft is null or (
    jsonb_typeof(draft) = 'object'
    and jsonb_typeof(draft -> 'ids') = 'array'
    and jsonb_array_length(draft -> 'ids') <= 15
    and not exists (
      select 1
        from jsonb_array_elements(draft -> 'ids') as e
       where jsonb_typeof(e) <> 'number'
          or (e)::numeric <= 0
          or (e)::numeric <> trunc((e)::numeric)
    )
    -- captain_id / vice_id: puuttuva tai null kelpaa; annettu = positiivinen
    -- kokonaisluku joka löytyy ids-listasta; pari ei saa olla sama pelaaja.
    and (
      draft -> 'captain_id' is null
      or jsonb_typeof(draft -> 'captain_id') = 'null'
      or (
        jsonb_typeof(draft -> 'captain_id') = 'number'
        and (draft ->> 'captain_id')::numeric > 0
        and (draft ->> 'captain_id')::numeric
            = trunc((draft ->> 'captain_id')::numeric)
        and draft -> 'ids' @> (draft -> 'captain_id')
      )
    )
    and (
      draft -> 'vice_id' is null
      or jsonb_typeof(draft -> 'vice_id') = 'null'
      or (
        jsonb_typeof(draft -> 'vice_id') = 'number'
        and (draft ->> 'vice_id')::numeric > 0
        and (draft ->> 'vice_id')::numeric
            = trunc((draft ->> 'vice_id')::numeric)
        and draft -> 'ids' @> (draft -> 'vice_id')
      )
    )
    and (
      draft -> 'captain_id' is null or draft -> 'vice_id' is null
      or jsonb_typeof(draft -> 'captain_id') = 'null'
      or jsonb_typeof(draft -> 'vice_id') = 'null'
      or (draft ->> 'captain_id') <> (draft ->> 'vice_id')
    )
  );
$$;

-- set_fpl_draft kuljettaa uudet kentät läpi. Leimaus pysyy palvelimella.
create or replace function public.set_fpl_draft(draft jsonb)
returns timestamptz
language plpgsql
security definer
set search_path = public
as $$
declare
  stamped jsonb;
  ts timestamptz := now();
begin
  if draft is null then
    update public.profiles set fpl_draft = null where id = auth.uid();
    return ts;
  end if;

  if not public.fpl_draft_is_valid(draft) then
    raise exception 'invalid fpl_draft shape';
  end if;

  stamped := jsonb_build_object(
    'v', 1,
    'ids', coalesce(draft -> 'ids', '[]'::jsonb),
    'updated_at', to_char(ts at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
  );
  -- Valinnaiset kentät vain jos annettu (ei null-roskaa vanhoihin drafteihin).
  if draft -> 'captain_id' is not null
     and jsonb_typeof(draft -> 'captain_id') = 'number' then
    stamped := stamped || jsonb_build_object('captain_id', draft -> 'captain_id');
  end if;
  if draft -> 'vice_id' is not null
     and jsonb_typeof(draft -> 'vice_id') = 'number' then
    stamped := stamped || jsonb_build_object('vice_id', draft -> 'vice_id');
  end if;

  update public.profiles set fpl_draft = stamped where id = auth.uid();
  return ts;
end;
$$;

-- Grantit ennallaan (funktioiden korvaus säilyttää ne, mutta eksplisiittisyys
-- on halvempaa kuin oletusten varassa eläminen).
revoke all on function public.set_fpl_draft(jsonb) from public;
revoke all on function public.set_fpl_draft(jsonb) from anon;
grant execute on function public.set_fpl_draft(jsonb) to authenticated;

-- VERIFY (aja SQL-editorissa migraation jälkeen):
--   1) Sarakkeet:
--      select column_name from information_schema.columns
--       where table_name='fpl_decisions' and column_name like '%grade%' or column_name in ('graded_at','model_points','user_points');
--   2) Immutability: UPDATE gradatulle riville (service-roolilla) -> exception.
--   3) Gradaus ennen deadlinea -> exception 'cannot grade before deadline'.
--   4) Draft kapteenilla:
--      set_fpl_draft({ids:[1,2,3], captain_id:1, vice_id:2})  -> ok
--      set_fpl_draft({ids:[1,2,3], captain_id:9})             -> exception (ei idseissä)
--      set_fpl_draft({ids:[1,2,3], captain_id:1, vice_id:1})  -> exception (sama)
--   5) Vanha muoto toimii yhä: set_fpl_draft({ids:[1,2,3]})   -> ok.
