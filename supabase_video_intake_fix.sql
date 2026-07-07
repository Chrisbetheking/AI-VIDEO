-- 视频采集入库修复：兼容 ECS video-intake、热度雷达汇总、AI审核记录
-- 在 Supabase SQL Editor 运行一次。

create extension if not exists pgcrypto;

create table if not exists heat_radar_items (
  id text primary key,
  workspace_id text not null default 'default',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table heat_radar_items add column if not exists workspace_id text not null default 'default';
alter table heat_radar_items add column if not exists date text default '';
alter table heat_radar_items add column if not exists platform text default '';
alter table heat_radar_items add column if not exists account_id text default '';
alter table heat_radar_items add column if not exists account_name text default '';
alter table heat_radar_items add column if not exists account_url text default '';
alter table heat_radar_items add column if not exists title text default '';
alter table heat_radar_items add column if not exists description text default '';
alter table heat_radar_items add column if not exists url text default '';
alter table heat_radar_items add column if not exists published_at text default '';
alter table heat_radar_items add column if not exists collected_at text default '';
alter table heat_radar_items add column if not exists like_count bigint default 0;
alter table heat_radar_items add column if not exists comment_count bigint default 0;
alter table heat_radar_items add column if not exists favorite_count bigint default 0;
alter table heat_radar_items add column if not exists share_count bigint default 0;
alter table heat_radar_items add column if not exists view_count bigint default 0;
alter table heat_radar_items add column if not exists heat_score bigint default 0;
alter table heat_radar_items add column if not exists hot_score bigint default 0;
alter table heat_radar_items add column if not exists keyword text default '';
alter table heat_radar_items add column if not exists thumbnail_url text default '';
alter table heat_radar_items add column if not exists is_pinned boolean default false;
alter table heat_radar_items add column if not exists source_mode text default '';
alter table heat_radar_items add column if not exists source_name text default '';
alter table heat_radar_items add column if not exists run_id text default '';
alter table heat_radar_items add column if not exists raw jsonb default '{}'::jsonb;
alter table heat_radar_items add column if not exists warnings jsonb default '[]'::jsonb;
alter table heat_radar_items add column if not exists deleted boolean default false;
alter table heat_radar_items add column if not exists created_at timestamptz default now();
alter table heat_radar_items add column if not exists updated_at timestamptz default now();

-- 如果旧表 tags 是 text[]，保持不动；如果没有 tags，新增 jsonb 版本。
alter table heat_radar_items add column if not exists tags jsonb default '[]'::jsonb;

create table if not exists heat_radar_account_reviews (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table heat_radar_account_reviews add column if not exists workspace_id text not null default 'default';
alter table heat_radar_account_reviews add column if not exists run_id text default '';
alter table heat_radar_account_reviews add column if not exists source_name text default '';
alter table heat_radar_account_reviews add column if not exists account_name text default '';
alter table heat_radar_account_reviews add column if not exists platform text default '';
alter table heat_radar_account_reviews add column if not exists account_url text default '';
alter table heat_radar_account_reviews add column if not exists decision text default '';
alter table heat_radar_account_reviews add column if not exists score integer default 0;
alter table heat_radar_account_reviews add column if not exists freshness_score integer default 0;
alter table heat_radar_account_reviews add column if not exists relevance_score integer default 0;
alter table heat_radar_account_reviews add column if not exists heat_score integer default 0;
alter table heat_radar_account_reviews add column if not exists latest_post_at text default '';
alter table heat_radar_account_reviews add column if not exists days_since_latest integer default 9999;
alter table heat_radar_account_reviews add column if not exists recent_items_count integer default 0;
alter table heat_radar_account_reviews add column if not exists reason text default '';
alter table heat_radar_account_reviews add column if not exists next_action text default '';
alter table heat_radar_account_reviews add column if not exists account_type text default '';
alter table heat_radar_account_reviews add column if not exists target_value text default '';
alter table heat_radar_account_reviews add column if not exists customer_intents jsonb default '[]'::jsonb;
alter table heat_radar_account_reviews add column if not exists content_opportunities jsonb default '[]'::jsonb;
alter table heat_radar_account_reviews add column if not exists risk_notes jsonb default '[]'::jsonb;
alter table heat_radar_account_reviews add column if not exists raw jsonb default '{}'::jsonb;
alter table heat_radar_account_reviews add column if not exists created_at timestamptz default now();
alter table heat_radar_account_reviews add column if not exists updated_at timestamptz default now();

create index if not exists idx_heat_items_workspace_created on heat_radar_items (workspace_id, created_at desc);
create index if not exists idx_heat_items_workspace_date_score on heat_radar_items (workspace_id, date, heat_score desc);
create index if not exists idx_heat_reviews_workspace_created on heat_radar_account_reviews (workspace_id, created_at desc);
