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
