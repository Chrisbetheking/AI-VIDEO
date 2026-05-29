-- 采集进度 / ECS Worker 命令队列 / 数字人供应商预留
create extension if not exists pgcrypto;

create table if not exists public.collector_runs (
  id text primary key,
  workspace_id text not null default 'default',
  run_id text not null unique,
  status text not null default 'running',
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
  started_at timestamptz,
  finished_at timestamptz,
  last_error text default '',
  raw jsonb default '{}'::jsonb,
  deleted boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists collector_runs_workspace_created_idx on public.collector_runs(workspace_id, created_at desc);
create index if not exists collector_runs_status_idx on public.collector_runs(status);

create table if not exists public.collector_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  run_id text not null,
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

create index if not exists collector_events_run_created_idx on public.collector_events(workspace_id, run_id, created_at desc);

create table if not exists public.collector_commands (
  id text primary key,
  workspace_id text not null default 'default',
  command_id text not null unique,
  status text not null default 'queued',
  limit integer default 1,
  account text default '',
  dry_run boolean default false,
  headful boolean default true,
  no_delay boolean default false,
  mode text default 'manual',
  message text default '',
  claimed_at timestamptz,
  finished_at timestamptz,
  raw jsonb default '{}'::jsonb,
  deleted boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists collector_commands_workspace_status_idx on public.collector_commands(workspace_id, status, created_at asc);

create table if not exists public.digital_human_provider_configs (
  id text primary key,
  workspace_id text not null default 'default',
  provider text not null,
  enabled boolean default false,
  display_name text default '',
  cost_note text default '',
  raw jsonb default '{}'::jsonb,
  deleted boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
