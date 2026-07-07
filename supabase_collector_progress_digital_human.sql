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
  "limit" integer default 1,
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


insert into public.digital_human_provider_configs
  (id, workspace_id, provider, enabled, display_name, cost_note, raw)
values
  (
    'default-preview-no-avatar',
    'default',
    'preview_no_avatar',
    true,
    '默认：无训练费素材成片',
    '0 训练费；今天优先跑通采集、豆包分析、文案、配音和素材视频。',
    '{"recommend_level":"first","stage":"today","note":"不依赖数字人平台"}'::jsonb
  ),
  (
    'default-heygen-api',
    'default',
    'heygen_api',
    false,
    'HeyGen 公共 Avatar API',
    '优先公共/模板 Avatar，不做专属训练；先小额测试。',
    '{"recommend_level":"api_test","stage":"no_training","note":"海外 API，中文效果需实测"}'::jsonb
  ),
  (
    'default-did-api',
    'default',
    'did_api',
    false,
    'D-ID 公共 Presenter API',
    '优先公共 Presenter/Trial，不做 Custom Avatar 训练。',
    '{"recommend_level":"backup","stage":"no_training","note":"数字人口播备用 API"}'::jsonb
  ),
  (
    'default-akool-api',
    'default',
    'akool_talking_photo',
    false,
    'AKOOL Talking Photo',
    'Talking Photo/Avatar 方向，先小样测试，不做定制训练。',
    '{"recommend_level":"backup","stage":"no_training","note":"海外备用"}'::jsonb
  ),
  (
    'default-local-musetalk-liveportrait',
    'default',
    'local_musetalk_liveportrait',
    false,
    '后期本地 MuseTalk / LivePortrait',
    '后期买 GPU 设备后接入，无平台训练费。',
    '{"recommend_level":"future","stage":"local_gpu","note":"长期降低数字人成本"}'::jsonb
  )
on conflict (id) do update set
  provider = excluded.provider,
  enabled = excluded.enabled,
  display_name = excluded.display_name,
  cost_note = excluded.cost_note,
  raw = excluded.raw,
  updated_at = now();
