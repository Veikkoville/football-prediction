-- GoalIQ Pro web-tilaukset (web-v1, 5.7.2026).
-- Aja Supabase SQL-editorissa (sama projekti kuin mobiili).
-- EI kosketa mobiilin profiles-tauluun — web-billing elää omassa taulussaan.

create table if not exists public.web_subscriptions (
  user_id uuid primary key references auth.users (id) on delete cascade,
  plan text not null check (plan in ('season', 'monthly')),
  status text not null default 'active'
    check (status in ('active', 'cancelled', 'past_due', 'expired')),
  current_period_end timestamptz,
  stripe_customer_id text,
  stripe_subscription_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- updated_at-trigger
create or replace function public.web_subscriptions_touch()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists web_subscriptions_touch on public.web_subscriptions;
create trigger web_subscriptions_touch
  before update on public.web_subscriptions
  for each row execute function public.web_subscriptions_touch();

-- RLS: käyttäjä saa LUKEA vain oman rivinsä; kirjoitus VAIN service-roolilla
-- (Streamlit-palvelin + Stripe-webhook käyttävät service-avainta).
alter table public.web_subscriptions enable row level security;

drop policy if exists "own subscription read" on public.web_subscriptions;
create policy "own subscription read"
  on public.web_subscriptions for select
  using (auth.uid() = user_id);

-- Ei insert/update-policyä authenticated-roolille tarkoituksella:
-- service_role ohittaa RLS:n → vain palvelin kirjoittaa.
