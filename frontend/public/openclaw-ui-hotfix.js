/* AI VIDEO V10.24 - wizard resume hotfix
 * Purpose:
 * 1) capture tts-first / one-scene job id when a generation starts
 * 2) keep polling/resume state in localStorage across route changes/refreshes
 * 3) provide a visible "继续上一次生成" panel even if React wizard resets to step 1
 */
(function () {
  'use strict';
  if (window.__AI_VIDEO_V10_24_RESUME_HOTFIX__) return;
  window.__AI_VIDEO_V10_24_RESUME_HOTFIX__ = true;

  var STORE_KEY = 'ai_video_wizard_resume_v10_24';
  var POLL_MS = 4000;
  var MAX_AGE_MS = 1000 * 60 * 60 * 24 * 3;
  var lastRenderAt = 0;
  var pollTimer = null;

  function now() { return Date.now(); }
  function isObj(x) { return x && typeof x === 'object'; }
  function safeJsonParse(s, fallback) { try { return JSON.parse(s); } catch (e) { return fallback; } }
  function readState() {
    var s = safeJsonParse(localStorage.getItem(STORE_KEY) || 'null', null);
    if (!isObj(s)) return null;
    if (s.updated_at && now() - Number(s.updated_at) > MAX_AGE_MS) return null;
    return s;
  }
  function writeState(patch) {
    var prev = readState() || {};
    var next = Object.assign({}, prev, patch || {}, { updated_at: now(), version: 'v10_24' });
    try { localStorage.setItem(STORE_KEY, JSON.stringify(next)); } catch (e) {}
    renderPanel();
    return next;
  }
  function clearState() {
    try { localStorage.removeItem(STORE_KEY); } catch (e) {}
    var el = document.getElementById('ai-video-v10-24-resume-panel');
    if (el) el.remove();
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }
  function text(x, fallback) {
    if (x === null || x === undefined) return fallback || '';
    var s = String(x).trim();
    return s || (fallback || '');
  }
  function findJobId(data) {
    if (!isObj(data)) return '';
    var keys = ['job_id', 'task_id', 'id', 'child_job_id'];
    for (var i = 0; i < keys.length; i++) {
      var v = text(data[keys[i]]);
      if (/^(tts_first|one_scene|full_ai|fal)_/.test(v)) return v;
    }
    if (isObj(data.job)) {
      var nested = findJobId(data.job);
      if (nested) return nested;
    }
    if (isObj(data.data)) {
      var nested2 = findJobId(data.data);
      if (nested2) return nested2;
    }
    return '';
  }
  function findVideoUrl(data) {
    if (!isObj(data)) return '';
    var keys = ['subtitled_video_url', 'final_video_url', 'video_url', 'url', 'raw_video_url'];
    for (var i = 0; i < keys.length; i++) {
      var v = text(data[keys[i]]);
      if (/^https?:\/\//.test(v) || v.indexOf('/api/') === 0) return v;
    }
    if (isObj(data.job)) {
      var nested = findVideoUrl(data.job);
      if (nested) return nested;
    }
    if (isObj(data.result)) {
      var nested2 = findVideoUrl(data.result);
      if (nested2) return nested2;
    }
    return '';
  }
  function normalizeStatus(data) {
    if (!isObj(data)) return '';
    return text(data.status || data.state || (data.job && data.job.status) || (data.result && data.result.status), 'running');
  }
  function jobEndpoint(jobId) {
    if (!jobId) return '';
    if (jobId.indexOf('tts_first_') === 0) return '/api/video/full-ai/tts-first/job/' + encodeURIComponent(jobId);
    if (jobId.indexOf('one_scene_') === 0) return '/api/video/full-ai/one-scene/job/' + encodeURIComponent(jobId);
    if (jobId.indexOf('full_ai_') === 0) return '/api/video/full-ai/job/' + encodeURIComponent(jobId);
    return '/api/video/full-ai/tts-first/job/' + encodeURIComponent(jobId);
  }
  function statusLabel(s) {
    s = text(s).toLowerCase();
    if (!s || s === 'running' || s === 'processing' || s === 'queued' || s === 'pending') return '生成中，正在继续轮询';
    if (s === 'completed' || s === 'done' || s === 'success' || s === 'succeeded') return '已完成';
    if (s === 'failed' || s === 'error') return '失败';
    return s;
  }
  function ensureCss() {
    if (document.getElementById('ai-video-v10-24-resume-css')) return;
    var style = document.createElement('style');
    style.id = 'ai-video-v10-24-resume-css';
    style.textContent = [
      '#ai-video-v10-24-resume-panel{position:fixed;right:18px;bottom:18px;z-index:2147483647;width:min(380px,calc(100vw - 36px));background:rgba(17,24,39,.96);color:#fff;border:1px solid rgba(255,255,255,.18);box-shadow:0 20px 60px rgba(0,0,0,.35);border-radius:18px;padding:14px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif}',
      '#ai-video-v10-24-resume-panel .ai-title{font-weight:800;font-size:15px;margin-bottom:6px}',
      '#ai-video-v10-24-resume-panel .ai-line{font-size:12px;line-height:1.45;color:rgba(255,255,255,.78);word-break:break-all;margin-top:4px}',
      '#ai-video-v10-24-resume-panel .ai-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}',
      '#ai-video-v10-24-resume-panel button,#ai-video-v10-24-resume-panel a{border:0;border-radius:10px;padding:8px 10px;font-size:12px;font-weight:700;cursor:pointer;text-decoration:none}',
      '#ai-video-v10-24-resume-panel .ai-primary{background:#fff;color:#111827}',
      '#ai-video-v10-24-resume-panel .ai-ghost{background:rgba(255,255,255,.12);color:#fff}',
      '#ai-video-v10-24-resume-panel video{width:100%;max-height:360px;margin-top:10px;border-radius:12px;background:#000}',
      '#ai-video-v10-24-resume-panel .ai-badge{display:inline-block;padding:3px 8px;border-radius:999px;background:rgba(16,185,129,.18);color:#bbf7d0;font-size:11px;font-weight:800;margin-left:6px}'
    ].join('\n');
    document.head.appendChild(style);
  }
  function renderPanel() {
    var st = readState();
    if (!st || !st.job_id) return;
    if (now() - lastRenderAt < 250) return;
    lastRenderAt = now();
    ensureCss();
    var el = document.getElementById('ai-video-v10-24-resume-panel');
    if (!el) {
      el = document.createElement('div');
      el.id = 'ai-video-v10-24-resume-panel';
      document.body.appendChild(el);
    }
    var video = text(st.video_url || st.subtitled_video_url || st.final_video_url || st.raw_video_url);
    var err = text(st.error || st.message || st.detail);
    var status = text(st.status, 'running');
    var created = st.created_at ? new Date(st.created_at).toLocaleString() : '';
    el.innerHTML = '';
    var title = document.createElement('div');
    title.className = 'ai-title';
    title.innerHTML = 'AI 视频任务恢复 <span class="ai-badge">V10.24</span>';
    el.appendChild(title);
    var line1 = document.createElement('div');
    line1.className = 'ai-line';
    line1.textContent = '状态：' + statusLabel(status) + (created ? ' ｜ ' + created : '');
    el.appendChild(line1);
    var line2 = document.createElement('div');
    line2.className = 'ai-line';
    line2.textContent = '任务：' + st.job_id;
    el.appendChild(line2);
    if (err && !video) {
      var line3 = document.createElement('div');
      line3.className = 'ai-line';
      line3.textContent = '错误：' + err;
      el.appendChild(line3);
    }
    if (video) {
      var v = document.createElement('video');
      v.controls = true;
      v.playsInline = true;
      v.src = video;
      el.appendChild(v);
    }
    var actions = document.createElement('div');
    actions.className = 'ai-actions';
    var btnPoll = document.createElement('button');
    btnPoll.className = 'ai-primary';
    btnPoll.textContent = video ? '刷新状态' : '继续轮询';
    btnPoll.onclick = function () { pollOnce(true); };
    actions.appendChild(btnPoll);
    if (video) {
      var a = document.createElement('a');
      a.className = 'ai-primary';
      a.href = video;
      a.target = '_blank';
      a.rel = 'noreferrer';
      a.textContent = '打开视频';
      actions.appendChild(a);
    }
    var btnCopy = document.createElement('button');
    btnCopy.className = 'ai-ghost';
    btnCopy.textContent = '复制任务ID';
    btnCopy.onclick = function () { navigator.clipboard && navigator.clipboard.writeText(st.job_id); };
    actions.appendChild(btnCopy);
    var btnClear = document.createElement('button');
    btnClear.className = 'ai-ghost';
    btnClear.textContent = '新建/清空';
    btnClear.onclick = clearState;
    actions.appendChild(btnClear);
    el.appendChild(actions);
  }
  async function pollOnce(force) {
    var st = readState();
    if (!st || !st.job_id) return;
    var status = text(st.status).toLowerCase();
    if (!force && (status === 'completed' || status === 'done' || status === 'success') && findVideoUrl(st)) return;
    var ep = jobEndpoint(st.job_id);
    if (!ep) return;
    try {
      var res = await fetch(ep, { credentials: 'include', cache: 'no-store' });
      var data = await res.clone().json().catch(function () { return {}; });
      var video = findVideoUrl(data);
      var next = {
        status: normalizeStatus(data),
        last_response: data,
        video_url: video || st.video_url || '',
        subtitled_video_url: text(data.subtitled_video_url || (data.job && data.job.subtitled_video_url), st.subtitled_video_url || ''),
        final_video_url: text(data.final_video_url || (data.job && data.job.final_video_url), st.final_video_url || ''),
        raw_video_url: text(data.raw_video_url || (data.job && data.job.raw_video_url), st.raw_video_url || ''),
        error: text(data.error || data.message || data.detail || (data.job && data.job.error), st.error || '')
      };
      if (video) next.status = next.status || 'completed';
      writeState(next);
    } catch (e) {
      writeState({ error: '轮询失败：' + (e && e.message ? e.message : String(e)) });
    }
  }
  function startPoller() {
    if (pollTimer) return;
    pollTimer = setInterval(function () { pollOnce(false); }, POLL_MS);
    setTimeout(function () { pollOnce(false); }, 500);
  }

  var originalFetch = window.fetch;
  window.fetch = async function(input, init) {
    var url = '';
    try { url = typeof input === 'string' ? input : (input && input.url) || ''; } catch (e) {}
    var method = text((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    var isStart = method === 'POST' && (/\/api\/video\/full-ai\/(one-scene|tts-first)\/start/.test(url));
    var isJob = method === 'GET' && (/\/api\/video\/full-ai\/(one-scene|tts-first)\/job\//.test(url));
    var response = await originalFetch.apply(this, arguments);
    try {
      if (isStart || isJob) {
        response.clone().json().then(function(data) {
          var jobId = findJobId(data) || (url.match(/\/job\/([^/?#]+)/) || [])[1] || '';
          if (!jobId) return;
          var video = findVideoUrl(data);
          writeState({
            job_id: jobId,
            created_at: (readState() && readState().created_at) || new Date().toISOString(),
            current_step: 4,
            endpoint: url,
            status: normalizeStatus(data),
            video_url: video || '',
            subtitled_video_url: text(data.subtitled_video_url || (data.job && data.job.subtitled_video_url), ''),
            final_video_url: text(data.final_video_url || (data.job && data.job.final_video_url), ''),
            raw_video_url: text(data.raw_video_url || (data.job && data.job.raw_video_url), ''),
            error: text(data.error || data.message || data.detail || (data.job && data.job.error), ''),
            last_response: data
          });
          startPoller();
        }).catch(function(){});
      }
    } catch (e) {}
    return response;
  };

  function boot() {
    var st = readState();
    if (st && st.job_id) {
      renderPanel();
      startPoller();
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.addEventListener('storage', function (e) { if (e.key === STORE_KEY) renderPanel(); });
})();


/* ================= AI VIDEO V10.25 KEYWORD + QUALITY HOTFIX ================= */
(function(){
  if (window.__AI_VIDEO_V10_25_QUALITY_HOTFIX__) return;
  window.__AI_VIDEO_V10_25_QUALITY_HOTFIX__ = true;
  var KEY='ai_video_v10_25_manual_keywords';
  function readKeywords(){try{return JSON.parse(localStorage.getItem(KEY)||'[]')||[]}catch(e){return[]}}
  function saveKeywords(arr){arr=Array.from(new Set((arr||[]).map(function(x){return String(x||'').trim()}).filter(Boolean))).slice(0,30);localStorage.setItem(KEY,JSON.stringify(arr));renderChips();return arr}
  function addKeywords(text){var arr=readKeywords();String(text||'').split(/[，,、\n\s]+/).forEach(function(x){x=x.trim();if(x&&arr.indexOf(x)<0)arr.push(x)});saveKeywords(arr)}
  function cfg(){return{subtitle_style:'DouyinCleanEmphasisV2',remove_punctuation:true,keyword_highlight:{enabled:true,keywords:readKeywords(),scale:1.22,palette:['yellow','orange','cyan']},transition_policy:{enabled:true,no_flash_cut:true,preferred:['cross_dissolve','slow_push_in','pull_out','horizontal_pan_match'],min_shot_seconds:2.2,max_shot_seconds:4.0},visual_policy:{enabled:true,malaysia_property_context:true,semantic_scene_mapping:true,sentiment_aware:true,no_repeat_scene_type:true,no_klcc_unless_explicit:true,no_ocean_unless_penang_langkawi_sabah:true,no_text_logos_signs:true}}}
  function ensurePanel(){if(document.getElementById('ai-v10-25-keyword-panel'))return;var css=document.createElement('style');css.textContent='#ai-v10-25-keyword-panel{position:fixed;right:18px;bottom:126px;z-index:2147483646;width:330px;background:rgba(17,24,39,.96);color:#fff;border:1px solid rgba(168,85,247,.45);border-radius:16px;box-shadow:0 18px 45px rgba(0,0,0,.25);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:14px}#ai-v10-25-keyword-panel .ttl{font-weight:800;font-size:15px;margin-bottom:8px}#ai-v10-25-keyword-panel .sub{font-size:12px;color:#cbd5e1;line-height:1.5;margin-bottom:10px}#ai-v10-25-keyword-panel textarea{width:100%;height:58px;border-radius:10px;border:1px solid #475569;background:#0f172a;color:#fff;padding:8px;font-size:13px;box-sizing:border-box}#ai-v10-25-keyword-panel button{border:0;border-radius:999px;padding:7px 10px;margin:6px 6px 0 0;font-weight:700;cursor:pointer}#ai-v10-25-keyword-panel .primary{background:#8b5cf6;color:#fff}#ai-v10-25-keyword-panel .ghost{background:#334155;color:#fff}#ai-v10-25-keyword-panel .chip{display:inline-flex;align-items:center;background:#f59e0b;color:#111827;font-weight:800;border-radius:999px;padding:4px 8px;margin:4px 4px 0 0;font-size:12px}#ai-v10-25-keyword-panel .chip i{font-style:normal;margin-left:6px;cursor:pointer}';document.head.appendChild(css);var box=document.createElement('div');box.id='ai-v10-25-keyword-panel';box.innerHTML='<div class="ttl">字幕重点词 <span style="color:#facc15">V10.25</span></div><div class="sub">手动输入要放大变色的词 生成时自动去标点 并按内容匹配餐厅 商场 地铁 诊所等画面</div><textarea placeholder="例如 生活配套 地铁 主干道 配套不足 长期持有"></textarea><div><button class="primary" data-act="add">加入重点词</button><button class="ghost" data-act="auto">从文案提取</button><button class="ghost" data-act="clear">清空</button></div><div id="ai-v10-25-chips" style="margin-top:8px"></div>';document.body.appendChild(box);box.addEventListener('click',function(e){var act=e.target&&e.target.getAttribute('data-act');if(act==='add'){addKeywords(box.querySelector('textarea').value);box.querySelector('textarea').value=''}if(act==='clear'){saveKeywords([])}if(act==='auto'){var allow=['生活配套','配套','地铁','主干道','交通','通勤','医疗','诊所','药房','教育','学校','华人区','房价','长期持有','配套不足','商场','超市','餐厅','户型','采光','阳台','投资','风险'];saveKeywords(readKeywords().concat(allow.filter(function(w){return(document.body.innerText||'').indexOf(w)>=0})))}if(e.target&&e.target.getAttribute('data-rm')){saveKeywords(readKeywords().filter(function(x){return x!==e.target.getAttribute('data-rm')}))}});renderChips()}
  function renderChips(){var chips=document.getElementById('ai-v10-25-chips');if(!chips)return;var arr=readKeywords();chips.innerHTML=arr.length?arr.map(function(x){return '<span class="chip">'+x+'<i data-rm="'+x+'">×</i></span>'}).join(''):'<span style="font-size:12px;color:#94a3b8">还没有手动重点词</span>'}
  function enhanceBody(body){if(!body||typeof body!=='object')return body;var c=cfg();body.subtitle_style=c.subtitle_style;body.remove_punctuation=true;body.manual_keywords=Array.from(new Set([].concat(body.manual_keywords||[],readKeywords())));body.highlight_keywords=body.manual_keywords;body.keyword_highlight=c.keyword_highlight;body.transition_policy=c.transition_policy;body.visual_policy=c.visual_policy;body.subtitle_rules={remove_punctuation:true,max_lines:2,max_keywords_per_sentence:3,style:'DouyinCleanEmphasisV2'};return body}
  var oldFetch=window.fetch;window.fetch=function(input,init){try{var url=String(typeof input==='string'?input:(input&&input.url)||'');var method=String((init&&init.method)||'GET').toUpperCase();if(method==='POST'&&/\/api\/video\/full-ai\/(one-scene|tts-first|start|script-ai)/.test(url)&&init&&init.body&&typeof init.body==='string'){var body=JSON.parse(init.body);init=Object.assign({},init,{body:JSON.stringify(enhanceBody(body))});console.log('AI_VIDEO_V10_25_ENHANCED_PAYLOAD',{url:url,keywords:readKeywords(),style:'DouyinCleanEmphasisV2'})}}catch(e){}return oldFetch.apply(this,arguments)};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ensurePanel);else ensurePanel();
})();
/* ================= END AI VIDEO V10.25 KEYWORD + QUALITY HOTFIX ================= */


/* ================= AI VIDEO V10.26 DEMAND ACCEPTANCE FRONTEND LOCK ================= */
(function(){
  if (window.__AI_VIDEO_V10_26_DEMAND_ACCEPTANCE_FRONTEND_LOCK__) return;
  window.__AI_VIDEO_V10_26_DEMAND_ACCEPTANCE_FRONTEND_LOCK__ = true;
  function cleanText(s){return String(s||'').replace(/[，。！？；：、,.!?;:"“”‘’（）()【】\[\]《》<>…]+/g,' ').replace(/\s+/g,' ').trim()}
  function findScript(body){
    if(!body||typeof body!=='object')return '';
    var keys=['script','script_text','copy','text','content','full_script','voice_script','narration'];
    var best='';
    keys.forEach(function(k){var v=cleanText(body[k]); if(v.length>best.length)best=v});
    ['script_segments','segments','subtitles','subtitle_cues','voice_segments','tts_segments'].forEach(function(k){
      var arr=body[k]; if(Array.isArray(arr)){var joined=arr.map(function(x){return typeof x==='string'?x:(x&&(x.text||x.clean_text||x.script||x.copy||x.content||x.sentence||''))}).map(cleanText).filter(Boolean).join(' '); if(joined.length>best.length)best=joined;}
    });
    return best;
  }
  function findDuration(body){
    var keys=['duration','duration_seconds','target_duration_seconds','audio_duration','tts_duration','voice_duration','real_audio_duration'];
    for(var i=0;i<keys.length;i++){var n=Number(body&&body[keys[i]]); if(n>=1&&n<=600)return n;}
    var s=findScript(body); return Math.max(12, Math.min(90, cleanText(s).length*0.32));
  }
  function normalize(body){
    if(!body||typeof body!=='object')return body;
    var script=findScript(body), dur=findDuration(body);
    if(script){['script','script_text','copy','text','content','full_script','voice_script','narration'].forEach(function(k){body[k]=script});}
    ['duration','duration_seconds','target_duration_seconds','audio_duration','tts_duration','voice_duration','real_audio_duration'].forEach(function(k){body[k]=dur});
    body.demand_acceptance_lock='v10_26';
    body.semantic_acceptance_required=true;
    body.subtitle_style='DouyinCleanEmphasisV2';
    body.remove_punctuation=true;
    body.subtitle_rules=Object.assign({}, body.subtitle_rules||{}, {remove_punctuation:true, style:'DouyinCleanEmphasisV2', max_lines:2, max_keywords_per_sentence:3});
    body.visual_policy=Object.assign({}, body.visual_policy||{}, {enabled:true, semantic_scene_mapping:true, sentiment_aware:true, no_repeat_scene_type:true, no_text_logos_signs:true, no_klcc_unless_explicit:true});
    body.transition_policy=Object.assign({}, body.transition_policy||{}, {enabled:true, no_flash_cut:true, preferred:['cross_dissolve','slow_push_in','pull_out','horizontal_pan_match'], min_shot_seconds:2.2, max_shot_seconds:4.0});
    return body;
  }
  var prevFetch=window.fetch;
  window.fetch=function(input,init){
    try{
      var url=String(typeof input==='string'?input:(input&&input.url)||'');
      var method=String((init&&init.method)||'GET').toUpperCase();
      if(method==='POST' && /\/api\/video\/full-ai\/(one-scene|tts-first|start|script-ai)/.test(url) && init && typeof init.body==='string'){
        var b=JSON.parse(init.body); b=normalize(b); init=Object.assign({},init,{body:JSON.stringify(b)}); console.log('AI_VIDEO_V10_26_DEMAND_ACCEPTANCE_PAYLOAD',{url:url,script:(b.script||'').slice(0,40),duration:b.duration,lock:b.demand_acceptance_lock});
      }
    }catch(e){}
    return prevFetch.apply(this,arguments);
  };
  function markPanel(){
    var p=document.getElementById('ai-v10-25-keyword-panel');
    if(p){var ttl=p.querySelector('.ttl'); if(ttl && ttl.innerHTML.indexOf('V10.26')<0) ttl.innerHTML='字幕重点词 <span style="color:#facc15">V10.26</span>';
      var sub=p.querySelector('.sub'); if(sub) sub.textContent='生成前会做需求验收 口播讲什么画面就必须对应什么 字幕自动去标点 关键词放大变色';}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',markPanel);else markPanel();
  setTimeout(markPanel,1200);
})();
/* ================= END AI VIDEO V10.26 DEMAND ACCEPTANCE FRONTEND LOCK ================= */

/* AI_VIDEO_V10_26B_REQUEST_BINDING_FIX: backend request body binding fixed */


/* ================= AI VIDEO V10.27 STRICT NARRATION BEST QUALITY FRONTEND LOCK ================= */
(function(){
  if(window.__AI_VIDEO_V10_27_STRICT_NARRATION_BEST_QUALITY__) return;
  window.__AI_VIDEO_V10_27_STRICT_NARRATION_BEST_QUALITY__ = true;
  var oldFetch = window.fetch;
  window.fetch = function(input, init){
    try{
      var url=String(typeof input==='string'?input:(input&&input.url)||'');
      var method=String((init&&init.method)||'GET').toUpperCase();
      if(method==='POST' && /\/api\/video\/full-ai\/(one-scene|tts-first|start|script-ai)/.test(url) && init && typeof init.body==='string'){
        var body=JSON.parse(init.body);
        body.strict_narration_alignment=true;
        body.no_invented_subtitles=true;
        body.no_repeated_subtitles=true;
        body.no_default_fallback_script=true;
        body.require_plan_acceptance_before_generation=true;
        body.demand_acceptance_lock='v10_27';
        body.transition_policy=Object.assign({}, body.transition_policy||{}, {enabled:true,no_flash_cut:true,forbidden:['cut','smooth_cut','flash_cut','hard_cut'],preferred:['cross_dissolve','slow_push_in','pull_out','horizontal_pan_match'],min_shot_seconds:2.2,max_shot_seconds:4.0});
        body.subtitle_rules=Object.assign({}, body.subtitle_rules||{}, {style:'DouyinCleanEmphasisV2',remove_punctuation:true,real_script_only:true,no_invented_text:true,max_keywords_per_sentence:3});
        init=Object.assign({}, init, {body:JSON.stringify(body)});
        console.log('AI_VIDEO_V10_27_STRICT_NARRATION_PAYLOAD',{url:url,lock:'v10_27'});
      }
    }catch(e){}
    return oldFetch.apply(this, arguments);
  };
})();
/* ================= END AI VIDEO V10.27 STRICT NARRATION BEST QUALITY FRONTEND LOCK ================= */


/* AI_VIDEO_V10_27B_START_MODEL_BINDING_FIX: start endpoint calls original start with TTSFirstStartRequest model after demand acceptance. */

/* AI_VIDEO_V10_27E_DIRECT_ORIGINAL_START_FIX: start bypasses stacked wrappers and calls the true original tts-first start with TTSFirstStartRequest after demand acceptance. */

;window.__AI_VIDEO_V10_27E_SHOT_OVERRIDES_DICT_FIX__=true;console.log('AI_VIDEO_V10_27E_SHOT_OVERRIDES_DICT_FIX');

;window.__AI_VIDEO_V10_27E_SCRIPT_TEXT_SCOPE_RUNTIME_FIX__=true;console.log('AI_VIDEO_V10_27E_SCRIPT_TEXT_SCOPE_RUNTIME_FIX');

;window.__AI_VIDEO_V10_27G_SAFE_RUNTIME_PROMPT_LOCK__=true;console.log('AI_VIDEO_V10_27G_SAFE_RUNTIME_PROMPT_LOCK');

/* AI_VIDEO_V10_27H_STRICT_FINAL_PROMPT_PURGE */

/* AI_VIDEO_V10_27I_RUNTIME_PROMPT_CLEANER */



/* AI VIDEO V10.29 - raw review / approved asset / slice panel
 * Purpose:
 * 1) After generation completes, show subtitle preview and raw preview separately.
 * 2) Human approves only the RAW no-subtitle source.
 * 3) Approved raw assets can be sliced without FAL cost.
 */
(function () {
  'use strict';
  if (window.__AI_VIDEO_V10_29_RAW_REVIEW_PANEL__) return;
  window.__AI_VIDEO_V10_29_RAW_REVIEW_PANEL__ = true;

  var STORE_KEY = 'ai_video_wizard_resume_v10_24';
  var PANEL_ID = 'ai-video-v10-29-raw-review-panel';
  var CSS_ID = 'ai-video-v10-29-raw-review-css';
  var ASSET_REFRESH_MS = 8000;
  var assetTimer = null;

  function isObj(x) { return x && typeof x === 'object'; }
  function text(x, fallback) {
    if (x === null || x === undefined) return fallback || '';
    var s = String(x).trim();
    return s || (fallback || '');
  }
  function safeJsonParse(s, fallback) { try { return JSON.parse(s); } catch (e) { return fallback; } }
  function readState() {
    try { return safeJsonParse(localStorage.getItem(STORE_KEY) || 'null', null); } catch (e) { return null; }
  }
  function findNested(data, keys) {
    if (!isObj(data)) return '';
    for (var i = 0; i < keys.length; i++) {
      var v = text(data[keys[i]]);
      if (v) return v;
    }
    if (isObj(data.job)) {
      var a = findNested(data.job, keys);
      if (a) return a;
    }
    if (isObj(data.result)) {
      var b = findNested(data.result, keys);
      if (b) return b;
    }
    if (isObj(data.data)) {
      var c = findNested(data.data, keys);
      if (c) return c;
    }
    return '';
  }
  function getJobId(st) {
    return text(st && (st.job_id || st.task_id || st.id));
  }
  function getStatus(st) {
    return text(st && st.status, 'running').toLowerCase();
  }
  function isCompleted(st) {
    var s = getStatus(st);
    return s === 'completed' || s === 'done' || s === 'success' || s === 'succeeded';
  }
  function getSubUrl(st) {
    return text(
      (st && (st.subtitled_video_url || st.final_video_url || st.video_url)) ||
      findNested(st && st.last_response, ['subtitled_video_url', 'final_video_url', 'video_url'])
    );
  }
  function getRawUrl(st) {
    return text(
      (st && st.raw_video_url) ||
      findNested(st && st.last_response, ['raw_video_url'])
    );
  }
  function ensureCss() {
    if (document.getElementById(CSS_ID)) return;
    var style = document.createElement('style');
    style.id = CSS_ID;
    style.textContent = [
      '#' + PANEL_ID + '{position:fixed;left:18px;bottom:18px;z-index:2147483646;width:min(440px,calc(100vw - 36px));max-height:88vh;overflow:auto;background:rgba(15,23,42,.97);color:#fff;border:1px solid rgba(255,255,255,.16);box-shadow:0 20px 60px rgba(0,0,0,.38);border-radius:18px;padding:14px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif}',
      '#' + PANEL_ID + ' *{box-sizing:border-box}',
      '#' + PANEL_ID + ' .v1029-title{font-size:15px;font-weight:900;margin-bottom:8px;display:flex;align-items:center;justify-content:space-between;gap:8px}',
      '#' + PANEL_ID + ' .v1029-badge{font-size:11px;font-weight:900;border-radius:999px;padding:3px 8px;background:rgba(59,130,246,.22);color:#bfdbfe}',
      '#' + PANEL_ID + ' .v1029-line{font-size:12px;line-height:1.45;color:rgba(255,255,255,.78);word-break:break-all;margin:5px 0}',
      '#' + PANEL_ID + ' .v1029-warn{font-size:12px;line-height:1.45;color:#fde68a;background:rgba(245,158,11,.14);border:1px solid rgba(245,158,11,.25);border-radius:12px;padding:8px;margin-top:8px}',
      '#' + PANEL_ID + ' .v1029-ok{font-size:12px;line-height:1.45;color:#bbf7d0;background:rgba(16,185,129,.14);border:1px solid rgba(16,185,129,.25);border-radius:12px;padding:8px;margin-top:8px}',
      '#' + PANEL_ID + ' .v1029-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}',
      '#' + PANEL_ID + ' video{width:100%;max-height:300px;border-radius:12px;background:#000;border:1px solid rgba(255,255,255,.12)}',
      '#' + PANEL_ID + ' .v1029-video-label{font-size:11px;font-weight:800;color:rgba(255,255,255,.76);margin:0 0 5px}',
      '#' + PANEL_ID + ' .v1029-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}',
      '#' + PANEL_ID + ' button,#' + PANEL_ID + ' a{border:0;border-radius:10px;padding:8px 10px;font-size:12px;font-weight:800;cursor:pointer;text-decoration:none}',
      '#' + PANEL_ID + ' .v1029-primary{background:#fff;color:#111827}',
      '#' + PANEL_ID + ' .v1029-green{background:#10b981;color:white}',
      '#' + PANEL_ID + ' .v1029-red{background:#ef4444;color:white}',
      '#' + PANEL_ID + ' .v1029-ghost{background:rgba(255,255,255,.12);color:#fff}',
      '#' + PANEL_ID + ' .v1029-section{margin-top:14px;padding-top:12px;border-top:1px solid rgba(255,255,255,.12)}',
      '#' + PANEL_ID + ' .v1029-asset{border:1px solid rgba(255,255,255,.12);border-radius:12px;padding:10px;margin-top:8px;background:rgba(255,255,255,.05)}',
      '#' + PANEL_ID + ' .v1029-input{width:78px;background:rgba(255,255,255,.1);color:#fff;border:1px solid rgba(255,255,255,.18);border-radius:8px;padding:7px;font-size:12px}',
      '#' + PANEL_ID + ' .v1029-minirow{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:8px}',
      '@media (max-width:720px){#' + PANEL_ID + '{left:10px;right:10px;width:auto;bottom:10px}#' + PANEL_ID + ' .v1029-grid{grid-template-columns:1fr}}'
    ].join('\n');
    document.head.appendChild(style);
  }

  async function postJson(url, body) {
    var res = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      credentials: 'include',
      cache: 'no-store',
      body: JSON.stringify(body || {})
    });
    var data = await res.json().catch(function(){ return {}; });
    if (!res.ok || data.ok === false) {
      throw new Error(text(data.detail || data.error || data.message, '请求失败'));
    }
    return data;
  }
  async function getJson(url) {
    var res = await fetch(url, { credentials:'include', cache:'no-store' });
    var data = await res.json().catch(function(){ return {}; });
    if (!res.ok || data.ok === false) throw new Error(text(data.detail || data.error || data.message, '请求失败'));
    return data;
  }

  async function approveRaw(jobId) {
    var note = prompt('确认保存烧字幕前 raw 原片？可填写质量备注：', '人工确认通过，保存 raw 无字幕原片');
    if (note === null) return;
    setMessage('正在保存 raw 原片...', 'warn');
    try {
      var data = await postJson('/api/video/assets/approve-raw', {
        job_id: jobId,
        quality_note: note || '人工确认通过'
      });
      setMessage('已保存 raw 原片：' + (data.asset && data.asset.raw_video_path ? data.asset.raw_video_path : jobId), 'ok');
      await loadAssets();
    } catch (e) {
      setMessage('保存失败：' + (e && e.message ? e.message : String(e)), 'warn');
    }
  }

  async function rejectRaw(jobId) {
    var reason = prompt('确认废弃这个视频？填写原因：', '画面质量不通过，不保存 raw 原片');
    if (reason === null) return;
    setMessage('正在标记废弃...', 'warn');
    try {
      await postJson('/api/video/assets/reject', {
        job_id: jobId,
        reason: reason || '人工拒绝'
      });
      setMessage('已标记 rejected，不会进入 raw 素材库。', 'ok');
      await loadAssets();
    } catch (e) {
      setMessage('废弃失败：' + (e && e.message ? e.message : String(e)), 'warn');
    }
  }

  function setMessage(msg, type) {
    var el = document.querySelector('#' + PANEL_ID + ' .v1029-message');
    if (!el) return;
    el.className = 'v1029-message ' + (type === 'ok' ? 'v1029-ok' : 'v1029-warn');
    el.textContent = msg;
    el.style.display = msg ? 'block' : 'none';
  }

  async function loadAssets() {
    var box = document.querySelector('#' + PANEL_ID + ' .v1029-assets');
    if (!box) return;
    try {
      var data = await getJson('/api/video/assets');
      var assets = Array.isArray(data.assets) ? data.assets : [];
      box.innerHTML = '';
      if (!assets.length) {
        var empty = document.createElement('div');
        empty.className = 'v1029-line';
        empty.textContent = '暂无已确认 raw 原片素材。';
        box.appendChild(empty);
        return;
      }
      assets.slice(0, 6).forEach(function(asset) {
        box.appendChild(renderAsset(asset));
      });
    } catch (e) {
      box.innerHTML = '<div class="v1029-warn">素材库加载失败：' + escapeHtml(e && e.message ? e.message : String(e)) + '</div>';
    }
  }

  function escapeHtml(s) {
    return String(s || '').replace(/[&<>"']/g, function(ch) {
      return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[ch];
    });
  }

  function renderAsset(asset) {
    var wrap = document.createElement('div');
    wrap.className = 'v1029-asset';

    var id = text(asset.asset_id);
    var rawPath = text(asset.raw_video_path);
    var duration = text(asset.ffprobe && asset.ffprobe.format && asset.ffprobe.format.duration);
    var rawUrl = text(asset.raw_video_url);

    wrap.innerHTML = [
      '<div class="v1029-line"><b>asset_id：</b>' + escapeHtml(id) + '</div>',
      '<div class="v1029-line"><b>raw：</b>' + escapeHtml(rawPath || rawUrl) + '</div>',
      duration ? '<div class="v1029-line"><b>duration：</b>' + escapeHtml(duration) + 's</div>' : '',
      '<div class="v1029-minirow">',
      '<label class="v1029-line">开始 <input class="v1029-input v1029-start" value="0" /></label>',
      '<label class="v1029-line">时长 <input class="v1029-input v1029-duration" value="5" /></label>',
      '</div>'
    ].join('');

    var row = document.createElement('div');
    row.className = 'v1029-actions';

    var btnSlice = document.createElement('button');
    btnSlice.className = 'v1029-green';
    btnSlice.textContent = '从 raw 切片';
    btnSlice.onclick = async function() {
      var start = parseFloat((wrap.querySelector('.v1029-start') || {}).value || '0');
      var dur = parseFloat((wrap.querySelector('.v1029-duration') || {}).value || '5');
      if (!isFinite(start) || start < 0) start = 0;
      if (!isFinite(dur) || dur <= 0) dur = 5;
      setMessage('正在从 raw 原片切片，不调用 FAL...', 'warn');
      try {
        var data = await postJson('/api/video/assets/' + encodeURIComponent(id) + '/slice', {
          start_seconds: start,
          duration_seconds: dur,
          note: '前端 V10.29 从 raw 无字幕原片切片'
        });
        var sl = data.slice || {};
        setMessage('切片完成 uses_fal=' + sl.uses_fal + '：' + sl.download_url, 'ok');
        if (sl.download_url) {
          window.open(sl.download_url, '_blank', 'noreferrer');
        }
      } catch (e) {
        setMessage('切片失败：' + (e && e.message ? e.message : String(e)), 'warn');
      }
    };
    row.appendChild(btnSlice);

    if (rawUrl) {
      var a = document.createElement('a');
      a.className = 'v1029-ghost';
      a.href = rawUrl;
      a.target = '_blank';
      a.rel = 'noreferrer';
      a.textContent = '打开 raw';
      row.appendChild(a);
    }

    wrap.appendChild(row);
    return wrap;
  }

  function renderPanel() {
    ensureCss();
    var st = readState() || {};
    var jobId = getJobId(st);
    var subUrl = getSubUrl(st);
    var rawUrl = getRawUrl(st);
    var completed = isCompleted(st);
    var status = text(st.status, '暂无任务');

    var el = document.getElementById(PANEL_ID);
    if (!el) {
      el = document.createElement('div');
      el.id = PANEL_ID;
      document.body.appendChild(el);
    }

    el.innerHTML = '';

    var title = document.createElement('div');
    title.className = 'v1029-title';
    title.innerHTML = '<span>人工确认 raw 原片</span><span class="v1029-badge">V10.29</span>';
    el.appendChild(title);

    var info = document.createElement('div');
    info.className = 'v1029-line';
    info.textContent = jobId ? ('任务：' + jobId + ' ｜ 状态：' + status) : '等待生成任务完成后自动显示确认按钮。';
    el.appendChild(info);

    var msg = document.createElement('div');
    msg.className = 'v1029-message v1029-warn';
    msg.style.display = 'none';
    el.appendChild(msg);

    if (jobId && completed) {
      if (!rawUrl) {
        var warn = document.createElement('div');
        warn.className = 'v1029-warn';
        warn.textContent = '当前任务没有 raw_video_url，不能保存为可复用 raw 原片。';
        el.appendChild(warn);
      }

      var grid = document.createElement('div');
      grid.className = 'v1029-grid';

      var left = document.createElement('div');
      left.innerHTML = '<div class="v1029-video-label">字幕版预览 video_url</div>';
      if (subUrl) {
        var v1 = document.createElement('video');
        v1.controls = true;
        v1.playsInline = true;
        v1.src = subUrl;
        left.appendChild(v1);
      } else {
        left.innerHTML += '<div class="v1029-line">暂无字幕版链接</div>';
      }
      grid.appendChild(left);

      var right = document.createElement('div');
      right.innerHTML = '<div class="v1029-video-label">无字幕 raw 原片 raw_video_url</div>';
      if (rawUrl) {
        var v2 = document.createElement('video');
        v2.controls = true;
        v2.playsInline = true;
        v2.src = rawUrl;
        right.appendChild(v2);
      } else {
        right.innerHTML += '<div class="v1029-line">暂无 raw 原片链接</div>';
      }
      grid.appendChild(right);

      el.appendChild(grid);

      var actions = document.createElement('div');
      actions.className = 'v1029-actions';

      var btnApprove = document.createElement('button');
      btnApprove.className = 'v1029-green';
      btnApprove.textContent = '确认保存 raw 原片';
      btnApprove.disabled = !rawUrl;
      btnApprove.onclick = function() { approveRaw(jobId); };
      actions.appendChild(btnApprove);

      var btnReject = document.createElement('button');
      btnReject.className = 'v1029-red';
      btnReject.textContent = '不满意，废弃';
      btnReject.onclick = function() { rejectRaw(jobId); };
      actions.appendChild(btnReject);

      if (subUrl) {
        var a1 = document.createElement('a');
        a1.className = 'v1029-primary';
        a1.href = subUrl;
        a1.target = '_blank';
        a1.rel = 'noreferrer';
        a1.textContent = '打开字幕版';
        actions.appendChild(a1);
      }

      if (rawUrl) {
        var a2 = document.createElement('a');
        a2.className = 'v1029-ghost';
        a2.href = rawUrl;
        a2.target = '_blank';
        a2.rel = 'noreferrer';
        a2.textContent = '打开 raw 原片';
        actions.appendChild(a2);
      }

      el.appendChild(actions);
    } else if (jobId) {
      var running = document.createElement('div');
      running.className = 'v1029-warn';
      running.textContent = '任务还没完成，完成后这里会出现“确认保存 raw 原片 / 废弃”按钮。';
      el.appendChild(running);
    }

    var section = document.createElement('div');
    section.className = 'v1029-section';
    section.innerHTML = '<div class="v1029-title"><span>已确认 raw 素材库</span><button class="v1029-ghost v1029-refresh-assets">刷新</button></div><div class="v1029-assets"><div class="v1029-line">正在加载...</div></div>';
    el.appendChild(section);

    var refresh = section.querySelector('.v1029-refresh-assets');
    if (refresh) refresh.onclick = loadAssets;

    loadAssets();
  }

  function boot() {
    renderPanel();
    if (!assetTimer) assetTimer = setInterval(renderPanel, ASSET_REFRESH_MS);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.addEventListener('storage', function(e) { if (e.key === STORE_KEY) setTimeout(renderPanel, 100); });

  var originalFetch = window.fetch;
  if (!window.__AI_VIDEO_V10_29_FETCH_WRAPPED__) {
    window.__AI_VIDEO_V10_29_FETCH_WRAPPED__ = true;
    window.fetch = async function(input, init) {
      var response = await originalFetch.apply(this, arguments);
      try {
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        var method = text((init && init.method) || (input && input.method) || 'GET').toUpperCase();
        if (
          /\/api\/video\/full-ai\/(one-scene|tts-first)\/job\//.test(url) ||
          /\/api\/video\/full-ai\/(one-scene|tts-first)\/start/.test(url) ||
          /\/api\/video\/assets/.test(url)
        ) {
          setTimeout(renderPanel, 600);
        }
      } catch(e) {}
      return response;
    };
  }
})();

