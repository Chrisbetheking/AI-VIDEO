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
