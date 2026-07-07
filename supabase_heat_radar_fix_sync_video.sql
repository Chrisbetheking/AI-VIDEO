-- 热度雷达修复：账号库多人同步 + 外部采集/视频分析字段
-- 在 Supabase SQL Editor 里运行一次。

create table if not exists heat_radar_accounts (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  name text,
  platform text,
  url text,
  tags text,
  notes text,
  pinned boolean default true,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists heat_radar_account_deletes (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  account_id text,
  deleted boolean default true,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists heat_radar_items (
  id text primary key,
  workspace_id text not null default 'default',
  date text,
  platform text,
  account_id text,
  account_name text,
  title text,
  description text,
  url text,
  published_at text,
  collected_at text,
  like_count integer default 0,
  comment_count integer default 0,
  favorite_count integer default 0,
  share_count integer default 0,
  view_count integer default 0,
  heat_score integer default 0,
  keyword text,
  tags jsonb default '[]'::jsonb,
  thumbnail_url text,
  is_pinned boolean default false,
  source_mode text,
  run_id text,
  source_name text,
  raw jsonb default '{}'::jsonb,
  warnings jsonb default '[]'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table heat_radar_items add column if not exists run_id text;
alter table heat_radar_items add column if not exists source_name text;
alter table heat_radar_items add column if not exists is_pinned boolean default false;

create table if not exists heat_daily_top3 (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  date text,
  summary text,
  top_items jsonb default '[]'::jsonb,
  analysis jsonb default '{}'::jsonb,
  keywords jsonb default '[]'::jsonb,
  accounts_count integer default 0,
  top_mode text,
  fallback_used boolean default false,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table heat_daily_top3 add column if not exists top_mode text;
alter table heat_daily_top3 add column if not exists fallback_used boolean default false;

create table if not exists heat_radar_account_reviews (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  run_id text,
  source_name text,
  account_name text,
  platform text,
  account_url text,
  decision text,
  score integer default 0,
  freshness_score integer default 0,
  relevance_score integer default 0,
  heat_score integer default 0,
  latest_post_at text,
  days_since_latest integer default 9999,
  recent_items_count integer default 0,
  reason text,
  next_action text,
  account_type text,
  target_value text,
  customer_intents jsonb default '[]'::jsonb,
  content_opportunities jsonb default '[]'::jsonb,
  risk_notes jsonb default '[]'::jsonb,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table heat_radar_account_reviews add column if not exists workspace_id text not null default 'default';
alter table heat_radar_account_reviews add column if not exists updated_at timestamptz default now();
alter table heat_radar_account_reviews add column if not exists account_type text;
alter table heat_radar_account_reviews add column if not exists target_value text;
alter table heat_radar_account_reviews add column if not exists customer_intents jsonb default '[]'::jsonb;
alter table heat_radar_account_reviews add column if not exists content_opportunities jsonb default '[]'::jsonb;
alter table heat_radar_account_reviews add column if not exists risk_notes jsonb default '[]'::jsonb;
alter table heat_radar_account_reviews add column if not exists raw jsonb default '{}'::jsonb;
