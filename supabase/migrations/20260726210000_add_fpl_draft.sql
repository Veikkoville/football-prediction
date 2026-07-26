-- Villen pyynto 26.7.2026: rate my team -draft samaksi webissa ja apissa.
--
-- Lahtotilanne: draft oli laitekohtainen JA muoto erosi alustoittain
--   web     localStorage['goaliq.fplDraftPicks']   = number[]
--   mobiili AsyncStorage['goaliq.fplDraftPicks']   = {GKP:[id,...], DEF:[...]}
-- Sama avaimen nimi, eri muoto, eri laite -> kaksi toisistaan tietamatonta
-- draftia. Nyt kanoninen muoto on litteä ID-lista ja totuus on tilin takana.
--
-- KIRJOITUSPOLKU: identtinen #66:n set_fpl_entry_id-kaavan kanssa ja samasta
-- syysta. profiles-taulussa EI ole UPDATE-policya authenticated-roolille, koska
-- RLS on rivi- ei saraketasoinen: policy avaisi kayttajalle myos oman
-- is_premium-sarakkeen (= ilmainen premium). Siksi kirjoitus kulkee SECURITY
-- DEFINER -funktion kautta, joka koskee VAIN fpl_draft-saraketta ja VAIN
-- auth.uid():n omalle riville. Olemassa olevat policyt/grantit koskemattomat.
--
-- LUKUPOLKU: olemassa oleva "oma rivi" -SELECT-policy kattaa uuden sarakkeen.
--
-- Deploy: supabase db push TAI SQL-editor (GO-REQUIRED, prod-skeema).

alter table public.profiles
  add column if not exists fpl_draft jsonb;

comment on column public.profiles.fpl_draft is
  'Rate my team -draft (cross-device). Muoto {"v":1,"ids":[int,...],"updated_at":"ISO"}. Kirjoitus vain set_fpl_draft().';

-- Muodon validointi: pidetaan kannassa asti, jotta rikkinainen klientti ei voi
-- taytta saraketta mielivaltaisella JSONilla. Enintaan 15 ID:ta (FPL-rosterin
-- koko) ja jokainen positiivinen kokonaisluku.
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
  );
$$;

alter table public.profiles
  drop constraint if exists profiles_fpl_draft_shape;
alter table public.profiles
  add constraint profiles_fpl_draft_shape
  check (public.fpl_draft_is_valid(fpl_draft)) not valid;

-- Kirjoitusfunktio: paivittaa vain oman rivin fpl_draft-sarakkeen.
-- NULL = tyhjenna draft. updated_at leimataan PALVELIMELLA, jotta laitteiden
-- kellopoikkeama ei voi tehda vanhasta draftista "uudempaa" synkassa.
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

  update public.profiles set fpl_draft = stamped where id = auth.uid();
  return ts;
end;
$$;

revoke all on function public.set_fpl_draft(jsonb) from public;
revoke all on function public.set_fpl_draft(jsonb) from anon;
grant execute on function public.set_fpl_draft(jsonb) to authenticated;

-- VERIFY (aja SQL-editorissa migraation jalkeen):
--   1) Sarake:
--      select column_name, data_type from information_schema.columns
--       where table_name = 'profiles' and column_name = 'fpl_draft';
--   2) Kirjoitus + palvelinleima (kirjautuneena clientilla):
--      supabase.rpc('set_fpl_draft', {draft: {ids: [1,2,3]}})
--      -> select fpl_draft from profiles;  -- {"v":1,"ids":[1,2,3],"updated_at":"..."}
--   3) Roskadata torjutaan:
--      supabase.rpc('set_fpl_draft', {draft: {ids: ['x']}})        -> exception
--      supabase.rpc('set_fpl_draft', {draft: {ids: [1,2,...,16]}}) -> exception
--   4) RLS-eristys: tili A:n kutsu ei muuta tili B:n rivia (funktio paivittaa
--      vain auth.uid():n rivin); anon ei voi kutsua funktiota lainkaan.
