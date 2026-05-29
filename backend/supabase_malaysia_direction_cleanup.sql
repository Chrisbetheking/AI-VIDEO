-- 只保留马来西亚/第二家园/海外置业方向：清理已经误入库的国内城市房产热点。
-- 运行后：雅安/名山/成都/四川等非目标内容会被软删除，不再进入热度雷达 Top5。

alter table public.heat_radar_items add column if not exists deleted boolean default false;

update public.heat_radar_items
set deleted = true,
    updated_at = now()
where coalesce(deleted, false) = false
  and (
    coalesce(title, '') || ' ' ||
    coalesce(description, '') || ' ' ||
    coalesce(account_name, '') || ' ' ||
    coalesce(keyword, '') || ' ' ||
    coalesce(url, '') || ' ' ||
    coalesce(raw::text, '')
  ) ~ '(雅安|名山|成都|四川|重庆|郑州|西安|北京|上海|广州|深圳|杭州|苏州|南京|厦门|合肥|武汉|长沙|昆明|海口|三亚|售楼部|电梯房|本地房源)'
  and (
    coalesce(title, '') || ' ' ||
    coalesce(description, '') || ' ' ||
    coalesce(account_name, '') || ' ' ||
    coalesce(keyword, '') || ' ' ||
    coalesce(url, '') || ' ' ||
    coalesce(raw::text, '')
  ) !~ '(马来西亚|大马|吉隆坡|新山|柔佛|槟城|雪兰莪|沙巴|沙捞越|MM2H|mm2h|第二家园|海外置业)';
