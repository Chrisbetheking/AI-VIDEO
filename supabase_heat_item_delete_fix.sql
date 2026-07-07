-- 热度雷达删除按钮修复：确保 heat_radar_items 支持软删除并清理已删除项过滤字段。
alter table if exists public.heat_radar_items add column if not exists deleted boolean default false;
create index if not exists heat_radar_items_workspace_deleted_created_idx
on public.heat_radar_items(workspace_id, deleted, created_at desc);

-- 可选：如果之前已经点过删除但前端旧 state 没刷新，不需要手动处理；部署新前端后会以 deleted=false 列表为准。
