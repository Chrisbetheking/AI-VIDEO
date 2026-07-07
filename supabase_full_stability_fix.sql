-- AI-VIDEO 一次性稳定修复 SQL
-- 作用：补齐热度雷达、文案历史、采集命令/进度/事件表字段；修复 0 分、script_versions 400、采集进度字段缺失等问题。
-- 可重复运行。

create extension if not exists pgcrypto;

-- 1) 热度雷达结果表：score / decision / 视频解析状态 / AI 维度
create table if not exists public.heat_radar_items (
  id text primary key default gen_random_uuid()::text,
  workspace_id text not null default 'default',
  account_name text default '',
  title text default '',
  url text default '',
  score numeric default 0,
  ai_score numeric default 0,
  decision text default '',
  reason text default '',
  raw jsonb default '{}'::jsonb,
  deleted boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.heat_radar_items
  add column if not exists workspace_id text default 'default',
  add column if not exists account_name text default '',
  add column if not exists platform text default '',
  add column if not exists title text default '',
  add column if not exists url text default '',
  add column if not exists video_url text default '',
  add column if not exists score numeric default 0,
  add column if not exists ai_score numeric default 0,
  add column if not exists decision text default '',
  add column if not exists reason text default '',
  add column if not exists intent_dimensions jsonb default '{}'::jsonb,
  add column if not exists buyer_dimensions jsonb default '[]'::jsonb,
  add column if not exists customer_intents jsonb default '[]'::jsonb,
  add column if not exists content_opportunities jsonb default '[]'::jsonb,
  add column if not exists matched_keywords jsonb default '[]'::jsonb,
  add column if not exists analysis_mode text default 'text_fallback',
  add column if not exists video_file_url text default '',
  add column if not exists r2_video_url text default '',
  add column if not exists video_download_status text default 'pending',
  add column if not exists video_download_error text default '',
  add column if not exists download_method text default '',
  add column if not exists like_count integer default 0,
  add column if not exists comment_count integer default 0,
  add column if not exists favorite_count integer default 0,
  add column if not exists share_count integer default 0,
  add column if not exists raw jsonb default '{}'::jsonb,
  add column if not exists deleted boolean default false,
  add column if not exists created_at timestamptz default now(),
  add column if not exists updated_at timestamptz default now();

update public.heat_radar_items
set
  workspace_id = coalesce(nullif(workspace_id, ''), 'default'),
  score = case
    when coalesce(score, 0) > 0 then score
    when raw #>> '{ai_review,score}' ~ '^[0-9]+(\.[0-9]+)?$' then (raw #>> '{ai_review,score}')::numeric
    when raw ->> 'score' ~ '^[0-9]+(\.[0-9]+)?$' then (raw ->> 'score')::numeric
    when raw ->> 'ai_score' ~ '^[0-9]+(\.[0-9]+)?$' then (raw ->> 'ai_score')::numeric
    when raw ->> 'business_score' ~ '^[0-9]+(\.[0-9]+)?$' then (raw ->> 'business_score')::numeric
    else coalesce(score, 0)
  end,
  ai_score = case
    when coalesce(ai_score, 0) > 0 then ai_score
    when raw #>> '{ai_review,score}' ~ '^[0-9]+(\.[0-9]+)?$' then (raw #>> '{ai_review,score}')::numeric
    when raw ->> 'score' ~ '^[0-9]+(\.[0-9]+)?$' then (raw ->> 'score')::numeric
    when raw ->> 'ai_score' ~ '^[0-9]+(\.[0-9]+)?$' then (raw ->> 'ai_score')::numeric
    when raw ->> 'business_score' ~ '^[0-9]+(\.[0-9]+)?$' then (raw ->> 'business_score')::numeric
    else coalesce(ai_score, 0)
  end,
  decision = case
    when coalesce(decision, '') <> '' then decision
    when coalesce(raw #>> '{ai_review,decision}', '') <> '' then raw #>> '{ai_review,decision}'
    when coalesce(raw ->> 'decision', '') <> '' then raw ->> 'decision'
    when coalesce(raw ->> 'action', '') <> '' then raw ->> 'action'
    else coalesce(decision, '')
  end,
  reason = case
    when coalesce(reason, '') <> '' then reason
    when coalesce(raw #>> '{ai_review,reason}', '') <> '' then raw #>> '{ai_review,reason}'
    when coalesce(raw ->> 'reason', '') <> '' then raw ->> 'reason'
    when coalesce(raw ->> 'summary', '') <> '' then raw ->> 'summary'
    else coalesce(reason, '')
  end,
  analysis_mode = coalesce(nullif(analysis_mode, ''), raw ->> 'ecs_analysis_mode', raw ->> 'analysis_mode', 'text_fallback'),
  video_download_status = coalesce(nullif(video_download_status, ''), raw ->> 'video_download_status', 'pending'),
  video_download_error = coalesce(nullif(video_download_error, ''), raw ->> 'video_download_error', ''),
  download_method = coalesce(nullif(download_method, ''), raw ->> 'download_method', raw ->> 'collector_method', ''),
  r2_video_url = coalesce(nullif(r2_video_url, ''), raw ->> 'r2_video_url', ''),
  updated_at = now();

-- 可选：隐藏旧 0 分脏数据，避免 Top5 继续显示 0 分旧记录。
update public.heat_radar_items
set deleted = true,
    updated_at = now()
where coalesce(deleted, false) = false
  and coalesce(score, 0) = 0
  and created_at < now() - interval '1 minute';

create index if not exists heat_radar_items_score_idx on public.heat_radar_items(score desc);
create index if not exists heat_radar_items_ai_score_idx on public.heat_radar_items(ai_score desc);
create index if not exists heat_radar_items_decision_idx on public.heat_radar_items(decision);
create index if not exists heat_radar_items_deleted_created_idx on public.heat_radar_items(deleted, created_at desc);
create index if not exists heat_radar_items_analysis_mode_idx on public.heat_radar_items(analysis_mode);

-- 2) 文案历史表：保存失败不再阻断接口；表字段也补齐。
create table if not exists public.script_versions (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  source text default '',
  title text default '',
  script text default '',
  prompt text default '',
  result jsonb default '{}'::jsonb,
  raw jsonb default '{}'::jsonb,
  input jsonb default '{}'::jsonb,
  output jsonb default '{}'::jsonb,
  deleted boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.script_versions
  add column if not exists workspace_id text default 'default',
  add column if not exists source text default '',
  add column if not exists title text default '',
  add column if not exists script text default '',
  add column if not exists prompt text default '',
  add column if not exists result jsonb default '{}'::jsonb,
  add column if not exists raw jsonb default '{}'::jsonb,
  add column if not exists input jsonb default '{}'::jsonb,
  add column if not exists output jsonb default '{}'::jsonb,
  add column if not exists deleted boolean default false,
  add column if not exists created_at timestamptz default now(),
  add column if not exists updated_at timestamptz default now();

update public.script_versions
set workspace_id = 'default'
where workspace_id is null;

create index if not exists script_versions_workspace_created_idx on public.script_versions(workspace_id, created_at desc);
create index if not exists script_versions_deleted_idx on public.script_versions(deleted);

-- 3) 采集命令表：网页下发任务，ECS 领取执行。
create table if not exists public.collector_commands (
  id text primary key default gen_random_uuid()::text,
  workspace_id text not null default 'default',
  command_id text default '',
  status text default 'queued',
  limit integer default 1,
  account text default '',
  dry_run boolean default false,
  headful boolean default true,
  no_delay boolean default false,
  mode text default 'manual',
  message text default '',
  raw jsonb default '{}'::jsonb,
  error text default '',
  deleted boolean default false,
  claimed_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.collector_commands
  add column if not exists workspace_id text default 'default',
  add column if not exists command_id text default '',
  add column if not exists status text default 'queued',
  add column if not exists limit integer default 1,
  add column if not exists account text default '',
  add column if not exists dry_run boolean default false,
  add column if not exists headful boolean default true,
  add column if not exists no_delay boolean default false,
  add column if not exists mode text default 'manual',
  add column if not exists message text default '',
  add column if not exists raw jsonb default '{}'::jsonb,
  add column if not exists error text default '',
  add column if not exists deleted boolean default false,
  add column if not exists claimed_at timestamptz,
  add column if not exists finished_at timestamptz,
  add column if not exists created_at timestamptz default now(),
  add column if not exists updated_at timestamptz default now();

create index if not exists collector_commands_workspace_status_idx on public.collector_commands(workspace_id, status, created_at asc);
create index if not exists collector_commands_status_idx on public.collector_commands(status);

-- 4) 采集进度主表。
create table if not exists public.collector_runs (
  id text primary key,
  workspace_id text not null default 'default',
  run_id text unique,
  status text default 'running',
  stage text default '',
  message text default '',
  current_account text default '',
  current_video text default '',
  total_accounts integer default 0,
  completed_accounts integer default 0,
  success_videos integer default 0,
  failed_videos integer default 0,
  mode text default 'ecs_worker',
  dry_run boolean default false,
  command_id text default '',
  started_at timestamptz default now(),
  finished_at timestamptz,
  last_error text default '',
  raw jsonb default '{}'::jsonb,
  deleted boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.collector_runs
  add column if not exists workspace_id text default 'default',
  add column if not exists run_id text,
  add column if not exists status text default 'running',
  add column if not exists stage text default '',
  add column if not exists message text default '',
  add column if not exists current_account text default '',
  add column if not exists current_video text default '',
  add column if not exists total_accounts integer default 0,
  add column if not exists completed_accounts integer default 0,
  add column if not exists success_videos integer default 0,
  add column if not exists failed_videos integer default 0,
  add column if not exists mode text default 'ecs_worker',
  add column if not exists dry_run boolean default false,
  add column if not exists command_id text default '',
  add column if not exists started_at timestamptz default now(),
  add column if not exists finished_at timestamptz,
  add column if not exists last_error text default '',
  add column if not exists raw jsonb default '{}'::jsonb,
  add column if not exists deleted boolean default false,
  add column if not exists created_at timestamptz default now(),
  add column if not exists updated_at timestamptz default now();

create unique index if not exists collector_runs_run_id_uq on public.collector_runs(run_id);
create index if not exists collector_runs_workspace_created_idx on public.collector_runs(workspace_id, created_at desc);

-- 5) 采集事件日志。
create table if not exists public.collector_events (
  id text primary key default gen_random_uuid()::text,
  workspace_id text not null default 'default',
  run_id text default '',
  stage text default '',
  level text default 'info',
  message text default '',
  account_name text default '',
  account_url text default '',
  video_title text default '',
  video_url text default '',
  progress jsonb default '{}'::jsonb,
  error_detail text default '',
  raw jsonb default '{}'::jsonb,
  deleted boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.collector_events
  add column if not exists workspace_id text default 'default',
  add column if not exists run_id text default '',
  add column if not exists stage text default '',
  add column if not exists level text default 'info',
  add column if not exists message text default '',
  add column if not exists account_name text default '',
  add column if not exists account_url text default '',
  add column if not exists video_title text default '',
  add column if not exists video_url text default '',
  add column if not exists progress jsonb default '{}'::jsonb,
  add column if not exists error_detail text default '',
  add column if not exists raw jsonb default '{}'::jsonb,
  add column if not exists deleted boolean default false,
  add column if not exists created_at timestamptz default now(),
  add column if not exists updated_at timestamptz default now();

create index if not exists collector_events_run_created_idx on public.collector_events(run_id, created_at desc);
create index if not exists collector_events_workspace_created_idx on public.collector_events(workspace_id, created_at desc);

notify pgrst, 'reload schema';
