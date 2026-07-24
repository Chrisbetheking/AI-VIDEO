-- V36 文案永久历史 + 多层查重字段。可重复执行。
create extension if not exists pgcrypto;

create table if not exists public.script_versions (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'default',
  source text default '',
  topic text default '',
  title text default '',
  hook text default '',
  script text default '',
  cta text default '',
  description text default '',
  tags jsonb default '[]'::jsonb,
  angle text default '',
  structure text default '',
  hook_type text default '',
  cta_type text default '',
  status text default 'generated',
  task_id text default '',
  fingerprint text default '',
  similarity_score numeric default 0,
  originality_score numeric default 100,
  duplicate_of text default '',
  dedup_report jsonb default '{}'::jsonb,
  metadata jsonb default '{}'::jsonb,
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
  add column if not exists topic text default '',
  add column if not exists title text default '',
  add column if not exists hook text default '',
  add column if not exists script text default '',
  add column if not exists cta text default '',
  add column if not exists description text default '',
  add column if not exists tags jsonb default '[]'::jsonb,
  add column if not exists angle text default '',
  add column if not exists structure text default '',
  add column if not exists hook_type text default '',
  add column if not exists cta_type text default '',
  add column if not exists status text default 'generated',
  add column if not exists task_id text default '',
  add column if not exists fingerprint text default '',
  add column if not exists similarity_score numeric default 0,
  add column if not exists originality_score numeric default 100,
  add column if not exists duplicate_of text default '',
  add column if not exists dedup_report jsonb default '{}'::jsonb,
  add column if not exists metadata jsonb default '{}'::jsonb,
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

create index if not exists script_versions_workspace_created_idx
on public.script_versions(workspace_id, created_at desc);

create index if not exists script_versions_workspace_fingerprint_idx
on public.script_versions(workspace_id, fingerprint);

create index if not exists script_versions_status_idx
on public.script_versions(status);

create index if not exists script_versions_deleted_idx
on public.script_versions(deleted);

notify pgrst, 'reload schema';
