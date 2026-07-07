-- 马来西亚方向过滤清理：删除雅安/名山/成都/四川等国内房产误入热度雷达的数据
-- 安全版：不依赖 topic/keyword/description 等固定字段，会自动检测 heat_radar_items 里实际存在的字段。

do $$
declare
  v_cols text[];
  v_text_expr text := '';
  v_col text;
  v_set_expr text;
  v_sql text;
  v_count integer := 0;
begin
  if to_regclass('public.heat_radar_items') is null then
    raise notice 'public.heat_radar_items 不存在，跳过清理';
    return;
  end if;

  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'heat_radar_items' and column_name = 'deleted'
  ) then
    alter table public.heat_radar_items add column deleted boolean default false;
  end if;

  select array_agg(column_name) into v_cols
  from information_schema.columns
  where table_schema = 'public' and table_name = 'heat_radar_items';

  foreach v_col in array array[
    'title','video_title','summary','content','description','notes','account_name','author_name',
    'platform','source_url','video_url','url','tags','keywords','keyword','raw'
  ] loop
    if v_col = any(v_cols) then
      if v_text_expr <> '' then
        v_text_expr := v_text_expr || ' || '' '' || ';
      end if;
      v_text_expr := v_text_expr || format('coalesce(%I::text, '''')', v_col);
    end if;
  end loop;

  if v_text_expr = '' then
    raise notice 'heat_radar_items 没有可用于判断方向的文本字段，跳过清理';
    return;
  end if;

  if 'updated_at' = any(v_cols) then
    v_set_expr := 'deleted = true, updated_at = now()';
  else
    v_set_expr := 'deleted = true';
  end if;

  v_sql := format($SQL$
    update public.heat_radar_items
    set %s
    where coalesce(deleted, false) = false
      and (%s) ~* %L
      and not ((%s) ~* %L)
  $SQL$,
    v_set_expr,
    v_text_expr,
    '(雅安|名山|成都|四川|重庆|西安|北京|上海|广州|深圳|杭州|国内房产|中国房产|售牌|挂牌|二手房|一手房|电梯房|学区房|楼盘|小区|县城|市区|买卖话题|出租)',
    v_text_expr,
    '(马来西亚|大马|吉隆坡|KL|Kuala Lumpur|雪兰莪|Selangor|槟城|Penang|新山|柔佛|Johor|马六甲|沙巴|MM2H|第二家园|海外置业|海外房产|马来生活|马来买房|陪读|留学|国际学校|Mont Kiara|Bukit Jalil|Malaysia)'
  );

  execute v_sql;
  get diagnostics v_count = row_count;
  raise notice '已软删除 % 条非马来西亚方向热度数据', v_count;
end $$;
