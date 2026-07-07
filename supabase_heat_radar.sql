-- 热度雷达 Supabase 表结构（可选）
-- 如果不执行，后端会自动降级写入 Render 本地 JSON；正式上线建议执行。

create table if not exists heat_radar_accounts (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  name text,
  platform text,
  url text,
  tags text,
  notes text,
  pinned boolean default false,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists heat_radar_items (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  date text,
  platform text,
  account_id text,
  account_name text,
  title text,
  description text,
  url text,
  published_at text,
  collected_at timestamptz default now(),
  like_count bigint default 0,
  comment_count bigint default 0,
  favorite_count bigint default 0,
  share_count bigint default 0,
  view_count bigint default 0,
  heat_score bigint default 0,
  keyword text,
  tags jsonb default '[]'::jsonb,
  thumbnail_url text,
  source_mode text,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists heat_daily_top3 (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  date text,
  summary text,
  top_items jsonb default '[]'::jsonb,
  analysis jsonb default '{}'::jsonb,
  keywords jsonb default '[]'::jsonb,
  accounts_count int default 0,
  raw jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists heat_radar_account_deletes (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  account_id text,
  deleted boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_heat_accounts_workspace_created on heat_radar_accounts(workspace_id, created_at desc);
create index if not exists idx_heat_items_workspace_date_score on heat_radar_items(workspace_id, date, heat_score desc);
create index if not exists idx_heat_daily_workspace_created on heat_daily_top3(workspace_id, created_at desc);
