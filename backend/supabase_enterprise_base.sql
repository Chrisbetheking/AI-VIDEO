-- Enterprise base patch for AI-VIDEO
-- Run this in Supabase SQL Editor once.

create table if not exists operation_logs (
  id text primary key,
  workspace_id text not null default 'default',
  event_type text default '',
  title text default '',
  level text default 'info',
  payload jsonb default '{}'::jsonb,
  deleted boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists jobs (
  id text primary key,
  workspace_id text not null default 'default',
  type text not null,
  title text default '',
  status text not null default 'queued',
  progress integer not null default 0,
  input jsonb default '{}'::jsonb,
  output jsonb default '{}'::jsonb,
  error text default '',
  deleted boolean default false,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists assets (
  id text primary key,
  workspace_id text not null default 'default',
  filename text not null,
  original_name text default '',
  kind text default '',
  url text default '',
  r2_url text default '',
  r2_key text default '',
  size_bytes bigint default 0,
  duration numeric default 0,
  width integer default 0,
  height integer default 0,
  folder text default 'self',
  source_type text default 'upload',
  raw jsonb default '{}'::jsonb,
  deleted boolean default false,
  created_by text default '',
  updated_by text default '',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_assets_workspace_created on assets (workspace_id, created_at desc);
create index if not exists idx_assets_workspace_kind on assets (workspace_id, kind);
create index if not exists idx_jobs_workspace_created on jobs (workspace_id, created_at desc);
create index if not exists idx_jobs_workspace_status on jobs (workspace_id, status);
create index if not exists idx_operation_logs_workspace_created on operation_logs (workspace_id, created_at desc);

-- Ensure heat radar tables contain fields used by the current backend.
create table if not exists heat_radar_accounts (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  name text default '',
  platform text default '抖音',
  url text default '',
  tags text default '',
  notes text default '',
  pinned boolean default true,
  raw jsonb default '{}'::jsonb,
  deleted boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table heat_radar_accounts add column if not exists workspace_id text not null default 'default';
alter table heat_radar_accounts add column if not exists deleted boolean default false;
alter table heat_radar_accounts add column if not exists updated_at timestamptz default now();
alter table heat_radar_accounts add column if not exists raw jsonb default '{}'::jsonb;
create index if not exists idx_heat_accounts_workspace_created on heat_radar_accounts (workspace_id, created_at desc);

create table if not exists heat_radar_items (
  id text primary key,
  workspace_id text not null default 'default',
  date text default '',
  platform text default '',
  account_id text default '',
  account_name text default '',
  account_url text default '',
  title text default '',
  description text default '',
  url text default '',
  published_at text default '',
  collected_at text default '',
  like_count integer default 0,
  comment_count integer default 0,
  favorite_count integer default 0,
  share_count integer default 0,
  view_count integer default 0,
  hot_score integer default 0,
  tags text[] default array[]::text[],
  is_pinned boolean default false,
  source_name text default '',
  run_id text default '',
  raw jsonb default '{}'::jsonb,
  deleted boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table heat_radar_items add column if not exists workspace_id text not null default 'default';
alter table heat_radar_items add column if not exists account_url text default '';
alter table heat_radar_items add column if not exists source_name text default '';
alter table heat_radar_items add column if not exists run_id text default '';
alter table heat_radar_items add column if not exists is_pinned boolean default false;
alter table heat_radar_items add column if not exists deleted boolean default false;
alter table heat_radar_items add column if not exists updated_at timestamptz default now();
create index if not exists idx_heat_items_workspace_created on heat_radar_items (workspace_id, created_at desc);

create table if not exists heat_daily_top3 (
  id text primary key,
  workspace_id text not null default 'default',
  date text default '',
  top_items jsonb default '[]'::jsonb,
  analysis jsonb default '{}'::jsonb,
  top_mode text default '',
  fallback_used boolean default false,
  raw jsonb default '{}'::jsonb,
  deleted boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table heat_daily_top3 add column if not exists workspace_id text not null default 'default';
alter table heat_daily_top3 add column if not exists top_mode text default '';
alter table heat_daily_top3 add column if not exists fallback_used boolean default false;
alter table heat_daily_top3 add column if not exists deleted boolean default false;
alter table heat_daily_top3 add column if not exists updated_at timestamptz default now();

create table if not exists heat_radar_account_reviews (
  id text primary key,
  workspace_id text not null default 'default',
  account_name text default '',
  platform text default '',
  account_url text default '',
  decision text default 'watch',
  score integer default 0,
  account_type text default '',
  target_value text default '',
  customer_intents text[] default array[]::text[],
  content_opportunities text[] default array[]::text[],
  risk_notes text[] default array[]::text[],
  reason text default '',
  next_action text default '',
  raw jsonb default '{}'::jsonb,
  deleted boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table heat_radar_account_reviews add column if not exists workspace_id text not null default 'default';
alter table heat_radar_account_reviews add column if not exists account_type text default '';
alter table heat_radar_account_reviews add column if not exists target_value text default '';
alter table heat_radar_account_reviews add column if not exists customer_intents text[] default array[]::text[];
alter table heat_radar_account_reviews add column if not exists content_opportunities text[] default array[]::text[];
alter table heat_radar_account_reviews add column if not exists risk_notes text[] default array[]::text[];
alter table heat_radar_account_reviews add column if not exists deleted boolean default false;
alter table heat_radar_account_reviews add column if not exists updated_at timestamptz default now();
create index if not exists idx_heat_reviews_workspace_created on heat_radar_account_reviews (workspace_id, created_at desc);
