-- AI-VIDEO 热度雷达：补齐视频解析/AI分数字段
-- 用途：解决前端 0 分、score/decision/reason 字段不存在、视频解析状态无法显示的问题。

create extension if not exists pgcrypto;

alter table public.heat_radar_items
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
  add column if not exists raw jsonb default '{}'::jsonb,
  add column if not exists deleted boolean default false,
  add column if not exists updated_at timestamptz default now();

-- 从 raw.ai_review / raw 顶层回填旧数据，避免前端继续显示 0 分。
update public.heat_radar_items
set
  score = case
    when coalesce(score, 0) > 0 then score
    when raw #>> '{ai_review,score}' ~ '^[0-9]+(\.[0-9]+)?$' then (raw #>> '{ai_review,score}')::numeric
    when raw ->> 'score' ~ '^[0-9]+(\.[0-9]+)?$' then (raw ->> 'score')::numeric
    when raw ->> 'ai_score' ~ '^[0-9]+(\.[0-9]+)?$' then (raw ->> 'ai_score')::numeric
    else coalesce(score, 0)
  end,
  ai_score = case
    when coalesce(ai_score, 0) > 0 then ai_score
    when raw #>> '{ai_review,score}' ~ '^[0-9]+(\.[0-9]+)?$' then (raw #>> '{ai_review,score}')::numeric
    when raw ->> 'score' ~ '^[0-9]+(\.[0-9]+)?$' then (raw ->> 'score')::numeric
    when raw ->> 'ai_score' ~ '^[0-9]+(\.[0-9]+)?$' then (raw ->> 'ai_score')::numeric
    else coalesce(ai_score, 0)
  end,
  decision = case
    when coalesce(decision, '') <> '' then decision
    when coalesce(raw #>> '{ai_review,decision}', '') <> '' then raw #>> '{ai_review,decision}'
    when coalesce(raw ->> 'decision', '') <> '' then raw ->> 'decision'
    else coalesce(decision, '')
  end,
  reason = case
    when coalesce(reason, '') <> '' then reason
    when coalesce(raw #>> '{ai_review,reason}', '') <> '' then raw #>> '{ai_review,reason}'
    when coalesce(raw ->> 'reason', '') <> '' then raw ->> 'reason'
    when coalesce(raw ->> 'summary', '') <> '' then raw ->> 'summary'
    else coalesce(reason, '')
  end,
  analysis_mode = coalesce(nullif(analysis_mode, ''), raw ->> 'ecs_analysis_mode', 'text_fallback'),
  video_download_status = coalesce(nullif(video_download_status, ''), raw ->> 'video_download_status', 'pending'),
  video_download_error = coalesce(nullif(video_download_error, ''), raw ->> 'video_download_error', ''),
  download_method = coalesce(nullif(download_method, ''), raw ->> 'download_method', raw ->> 'collector_method', ''),
  r2_video_url = coalesce(nullif(r2_video_url, ''), raw ->> 'r2_video_url', ''),
  updated_at = now();

create index if not exists heat_radar_items_score_idx
on public.heat_radar_items(score desc);

create index if not exists heat_radar_items_ai_score_idx
on public.heat_radar_items(ai_score desc);

create index if not exists heat_radar_items_decision_idx
on public.heat_radar_items(decision);

create index if not exists heat_radar_items_deleted_created_idx
on public.heat_radar_items(deleted, created_at desc);

create index if not exists heat_radar_items_analysis_mode_idx
on public.heat_radar_items(analysis_mode);

notify pgrst, 'reload schema';
