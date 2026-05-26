-- Optional Supabase tables for Heat Radar automation / OpenClaw ingestion
create table if not exists heat_radar_account_reviews (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz default now(),
  run_id text,
  source_name text,
  account_name text,
  platform text,
  account_url text,
  decision text,
  score int,
  freshness_score int,
  relevance_score int,
  heat_score int,
  latest_post_at text,
  days_since_latest int,
  recent_items_count int,
  reason text,
  next_action text
);

create index if not exists idx_heat_radar_account_reviews_created_at on heat_radar_account_reviews(created_at desc);
create index if not exists idx_heat_radar_account_reviews_decision on heat_radar_account_reviews(decision);
