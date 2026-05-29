-- 文案版本表兼容修复：让 /api/generate-copy 保存历史不再 400
create extension if not exists pgcrypto;

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

-- 防止历史数据里 null workspace_id 导致接口查询异常
update public.script_versions
set workspace_id = 'default'
where workspace_id is null;

create index if not exists script_versions_workspace_created_idx
on public.script_versions(workspace_id, created_at desc);

create index if not exists script_versions_deleted_idx
on public.script_versions(deleted);

notify pgrst, 'reload schema';
