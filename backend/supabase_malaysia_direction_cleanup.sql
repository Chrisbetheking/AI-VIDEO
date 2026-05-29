-- 马来西亚方向清理：把已经误入热度池的国内房产/本地楼盘内容软删除。
-- 重点：即使账号 tags/raw 里有“马来西亚房产”，只要标题明显是雅安/名山/成都等国内房源，也会隐藏。

alter table if exists public.heat_radar_items add column if not exists deleted boolean default false;
create index if not exists heat_radar_items_workspace_deleted_created_idx
on public.heat_radar_items(workspace_id, deleted, created_at desc);

-- 1) 标题/主题本身是国内楼盘，且标题没有马来西亚强相关词：直接软删除。
update public.heat_radar_items
set deleted = true,
    updated_at = now()
where coalesce(deleted, false) = false
  and (
    coalesce(title, '') || ' ' ||
    coalesce(topic, '')
  ) ~ '(雅安|名山|成都|四川|重庆|郑州|西安|北京|上海|广州|深圳|杭州|苏州|南京|厦门|合肥|武汉|长沙|昆明|海口|三亚|售楼部|电梯房|本地房源|国内房产|县城房|本地楼盘)'
  and (
    coalesce(title, '') || ' ' ||
    coalesce(topic, '')
  ) !~* '(马来西亚|大马|吉隆坡|新山|柔佛|槟城|雪兰莪|沙巴|沙捞越|MM2H|第二家园|海外置业|海外房产|Kuala Lumpur|Johor|Penang|KL)';

-- 2) 全文没有任何马来西亚/海外置业强相关词，也软删除，避免纯国内房产混入。
update public.heat_radar_items
set deleted = true,
    updated_at = now()
where coalesce(deleted, false) = false
  and (
    coalesce(title, '') || ' ' ||
    coalesce(topic, '') || ' ' ||
    coalesce(description, '') || ' ' ||
    coalesce(account_name, '') || ' ' ||
    coalesce(keyword, '') || ' ' ||
    coalesce(url, '') || ' ' ||
    coalesce(raw::text, '')
  ) !~* '(马来西亚|大马|吉隆坡|新山|柔佛|槟城|雪兰莪|沙巴|沙捞越|MM2H|第二家园|海外置业|海外房产|Kuala Lumpur|Johor|Penang|KL)';
