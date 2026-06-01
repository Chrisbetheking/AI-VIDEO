-- 素材用途分组：人物素材 / 内容素材
alter table if exists assets add column if not exists usage_role text default 'content';

update assets
set usage_role = case
  when coalesce(folder, '') = 'digital_human' then 'avatar'
  when lower(coalesce(filename, '')) like 'digital_human_%' then 'avatar'
  when lower(coalesce(filename, '')) like '%avatar%' then 'avatar'
  when lower(coalesce(filename, '')) like '%portrait%' then 'avatar'
  when lower(coalesce(original_name, '')) like '%口播%' then 'avatar'
  when lower(coalesce(original_name, '')) like '%真人%' then 'avatar'
  when lower(coalesce(original_name, '')) like '%数字人%' then 'avatar'
  else coalesce(nullif(usage_role, ''), 'content')
end
where usage_role is null or usage_role = '' or usage_role not in ('avatar', 'content');
