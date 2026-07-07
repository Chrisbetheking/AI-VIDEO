-- AI-VIDEO 学习记忆库 Supabase 表结构
-- Supabase SQL Editor 里执行一次即可。

create table if not exists customer_profiles (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  industry text,
  audience text,
  selling_points text,
  style text,
  lead_region text,
  conversion_goal text,
  trend_keywords text,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists competitor_accounts (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  name text,
  platform text,
  url text,
  positioning text,
  notes text,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists competitor_videos (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  source_name text,
  platform text default 'douyin',
  source_url text,
  manual_text text,
  transcript text,
  summary text,
  structure jsonb default '[]'::jsonb,
  hooks jsonb default '[]'::jsonb,
  selling_points jsonb default '[]'::jsonb,
  status text,
  collector_status text,
  collected_video_url text,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists trend_radar_records (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  industry text,
  audience text,
  region text,
  keywords jsonb default '[]'::jsonb,
  summary text,
  hot_topics jsonb default '[]'::jsonb,
  content_angles jsonb default '[]'::jsonb,
  shooting_suggestions jsonb default '[]'::jsonb,
  monitor_keywords jsonb default '[]'::jsonb,
  next_actions jsonb default '[]'::jsonb,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists script_versions (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  title text,
  hook text,
  script text,
  description text,
  tags jsonb default '[]'::jsonb,
  shots jsonb default '[]'::jsonb,
  source text,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists media_assets (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  filename text,
  original_name text,
  kind text,
  url text,
  size_bytes bigint,
  tags jsonb default '[]'::jsonb,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists learning_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  event_type text,
  title text,
  payload jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_customer_profiles_workspace_created on customer_profiles(workspace_id, created_at desc);
create index if not exists idx_competitor_accounts_workspace_created on competitor_accounts(workspace_id, created_at desc);
create index if not exists idx_competitor_videos_workspace_created on competitor_videos(workspace_id, created_at desc);
create index if not exists idx_trend_radar_workspace_created on trend_radar_records(workspace_id, created_at desc);
create index if not exists idx_script_versions_workspace_created on script_versions(workspace_id, created_at desc);
create index if not exists idx_learning_events_workspace_created on learning_events(workspace_id, created_at desc);
