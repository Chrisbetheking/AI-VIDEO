#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

START = "<!-- AI_VIDEO_REVIEW_GATE_UI_START -->"
END = "<!-- AI_VIDEO_REVIEW_GATE_UI_END -->"

BLOCK = r'''
<!-- AI_VIDEO_REVIEW_GATE_UI_START -->
<style>
.reviewGatePanel{
  max-width:1380px;
  margin:0 auto 20px;
  padding:0;
}
.reviewGateCard{
  background:#fff;
  border:1px solid #eadcff;
  border-radius:24px;
  padding:20px 22px;
  box-shadow:0 16px 42px rgba(15,23,42,.07);
}
.reviewGateHead{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:14px;
  flex-wrap:wrap;
}
.reviewGateHead h2{margin:0;font-size:22px}
.reviewGateBadge{
  display:inline-flex;
  align-items:center;
  padding:7px 12px;
  border-radius:999px;
  font-weight:950;
  font-size:13px;
  background:#f1f5f9;
  color:#475569;
}
.reviewGateBadge.pending{background:#fef3c7;color:#92400e}
.reviewGateBadge.failed,.reviewGateBadge.rejected{background:#fee2e2;color:#b91c1c}
.reviewGateBadge.approved{background:#dcfce7;color:#166534}
.reviewGateGrid{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:14px;
  margin-top:16px;
}
.reviewGateBox{
  border:1px solid #e5e7eb;
  background:#f8fafc;
  border-radius:16px;
  padding:14px;
  min-height:110px;
}
.reviewGateBox b{display:block;margin-bottom:8px}
.reviewGateActions{
  display:flex;
  gap:10px;
  flex-wrap:wrap;
  margin-top:14px;
}
.reviewGateActions button{
  border:0;
  border-radius:14px;
  padding:12px 16px;
  font-weight:950;
  cursor:pointer;
  color:#fff;
}
.reviewRun{background:#2563eb}
.reviewApprove{background:#16a34a}
.reviewReject{background:#dc2626}
.reviewGateIssues{
  margin:8px 0 0;
  padding-left:20px;
  color:#475569;
  line-height:1.75;
}
.reviewGateHint{
  color:#64748b;
  font-weight:700;
  margin:8px 0 0;
}
@media(max-width:900px){
  .reviewGateGrid{grid-template-columns:1fr}
}
</style>
<script>
(function(){
  const REVIEW_API_BASE = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE
    : 'https://ai-video.47-76-143-158.sslip.io'

  let currentReview = null

  function escapeHtml(value){
    return String(value == null ? '' : value)
      .replaceAll('&','&amp;')
      .replaceAll('<','&lt;')
      .replaceAll('>','&gt;')
      .replaceAll('"','&quot;')
      .replaceAll("'",'&#039;')
  }

  function reviewJobId(){
    const el = document.getElementById('jobId')
    return el ? el.value.trim() : ''
  }

  async function reviewFetch(path, body, method='POST'){
    const res = await fetch(REVIEW_API_BASE + path, {
      method,
      headers: body ? {'Content-Type':'application/json'} : undefined,
      body: body ? JSON.stringify(body) : undefined
    })
    const text = await res.text()
    let data = {}
    try{ data = text ? JSON.parse(text) : {} }catch{ data = {raw:text} }
    if(!res.ok){
      throw new Error(data.detail || data.message || data.error || text || `HTTP ${res.status}`)
    }
    return data
  }

  function packageButtons(){
    return [
      document.querySelector('button[onclick="makeCover()"]'),
      document.querySelector('button[onclick="makeXhs()"]')
    ].filter(Boolean)
  }

  function setPackagingEnabled(enabled){
    packageButtons().forEach(btn => {
      btn.disabled = !enabled
      btn.title = enabled ? '' : '视频尚未人工通过审查'
    })
  }

  function normalizedStatus(report){
    const status = String(report?.status || 'not_reviewed')
    if(status === 'review_pending_human') return 'pending'
    if(status === 'review_failed') return 'failed'
    return status
  }

  function statusText(report){
    const status = String(report?.status || 'not_reviewed')
    const map = {
      not_reviewed:'尚未审查',
      reviewing:'自动审查中',
      review_pending_human:'自动检查通过 等待人工确认',
      review_failed:'自动检查发现问题',
      approved:'已通过 已解锁封面',
      rejected:'已退回修改',
      review_error:'审查异常'
    }
    return map[status] || status
  }

  function issueText(issue){
    const start = Number(issue?.start || 0)
    const end = Number(issue?.end || 0)
    const range = end > start ? `${start.toFixed(1)}s-${end.toFixed(1)}s ` : ''
    return `${range}${issue?.description || issue?.detail || issue?.type || '未描述问题'}`
  }

  function renderReview(report){
    currentReview = report || {}
    const badge = document.getElementById('reviewGateBadge')
    const summary = document.getElementById('reviewGateSummary')
    const score = document.getElementById('reviewGateScore')
    const issues = document.getElementById('reviewGateIssues')
    const approved = report?.status === 'approved' &&
      report?.approved === true &&
      report?.packaging_unlocked === true

    if(badge){
      badge.className = 'reviewGateBadge ' + normalizedStatus(report)
      badge.textContent = statusText(report)
    }
    if(summary){
      summary.textContent = report?.summary ||
        (report?.status === 'not_reviewed'
          ? '视频生成完成后必须先审查，未通过时不会生成封面和小红书图文。'
          : '等待审查结果')
    }
    if(score){
      const machine = report?.mechanical?.score
      const ai = report?.ai_review?.score
      score.textContent = `综合 ${report?.overall_score ?? '-'} / 机械 ${machine ?? '-'} / 豆包 ${ai ?? '-'}`
    }
    if(issues){
      const list = Array.isArray(report?.issues) ? report.issues : []
      issues.innerHTML = list.length
        ? list.slice(0,12).map(x => `<li>${escapeHtml(issueText(x))}</li>`).join('')
        : '<li>暂未发现问题或尚未执行审查</li>'
    }

    setPackagingEnabled(approved)

    if(report?.status === 'reviewing'){
      window.clearTimeout(window.__aiVideoReviewPollTimer)
      window.__aiVideoReviewPollTimer = window.setTimeout(window.refreshVideoReview, 5000)
    }

    const approveBtn = document.getElementById('reviewApproveBtn')
    if(approveBtn){
      approveBtn.disabled = report?.status !== 'review_pending_human'
      approveBtn.title = approveBtn.disabled
        ? '自动审查通过后才能人工批准'
        : ''
    }
  }

  function ensurePanel(){
    if(document.getElementById('reviewGatePanel')) return
    const hero = document.querySelector('.hero')
    const main = document.querySelector('main')
    const panel = document.createElement('section')
    panel.id = 'reviewGatePanel'
    panel.className = 'reviewGatePanel'
    panel.innerHTML = `
      <div class="reviewGateCard">
        <div class="reviewGateHead">
          <h2>视频审查闸门</h2>
          <span id="reviewGateBadge" class="reviewGateBadge">尚未审查</span>
        </div>
        <p class="reviewGateHint">视频生成完成 → 机械质检 → 豆包审片 → 人工确认 → 自动生成9:16封面。未通过时封面和图文按钮保持锁定。</p>
        <div class="reviewGateGrid">
          <div class="reviewGateBox">
            <b>审查结论</b>
            <div id="reviewGateSummary">请选择或读取一个已完成的视频任务</div>
            <div id="reviewGateScore" style="margin-top:10px;font-weight:900;color:#475569">综合 - / 机械 - / 豆包 -</div>
          </div>
          <div class="reviewGateBox">
            <b>发现的问题</b>
            <ul id="reviewGateIssues" class="reviewGateIssues"><li>尚未执行审查</li></ul>
          </div>
        </div>
        <div class="reviewGateActions">
          <button class="reviewRun" onclick="runVideoReview()">自动审查视频</button>
          <button id="reviewApproveBtn" class="reviewApprove" onclick="approveVideoAndMakeCover()" disabled>通过并生成9:16封面</button>
          <button class="reviewReject" onclick="rejectVideoReview()">退回修改</button>
        </div>
      </div>`
    if(hero && hero.parentNode){
      hero.insertAdjacentElement('afterend', panel)
    }else if(main){
      main.prepend(panel)
    }else{
      document.body.prepend(panel)
    }
  }

  window.refreshVideoReview = async function(){
    ensurePanel()
    const jobId = reviewJobId()
    if(!jobId){
      renderReview({status:'not_reviewed'})
      return
    }
    try{
      const data = await reviewFetch(`/api/video/review/${encodeURIComponent(jobId)}`, null, 'GET')
      renderReview(data)
    }catch(e){
      renderReview({status:'review_error', summary:'读取审查状态失败：' + e.message})
    }
  }

  window.runVideoReview = async function(){
    const jobId = reviewJobId()
    if(!jobId){
      alert('请先读取最新成片或填写 Job ID')
      return
    }
    ensurePanel()
    renderReview({status:'reviewing', summary:'正在执行机械质检和豆包视频理解审查'})
    try{
      const data = await reviewFetch(
        `/api/video/review/${encodeURIComponent(jobId)}/run`,
        {force_ai:true, force:true}
      )
      renderReview(data)
      if(typeof log === 'function') log(data)
    }catch(e){
      renderReview({status:'review_error', summary:'审查失败：' + e.message})
      if(typeof log === 'function') log('审查失败：' + e.message)
    }
  }

  window.approveVideoAndMakeCover = async function(){
    const jobId = reviewJobId()
    if(!jobId) return
    const titleEl = document.getElementById('title')
    const keywordsEl = document.getElementById('keywords')
    const styleEl = document.getElementById('style')
    const ctaEl = document.getElementById('cta')
    try{
      const data = await reviewFetch(
        `/api/video/review/${encodeURIComponent(jobId)}/approve`,
        {
          reviewer:'human',
          generate_cover:true,
          title:titleEl?.value || '',
          keywords:(keywordsEl?.value || '').split(/[,，\s]+/).filter(Boolean),
          style:styleEl?.value || '专业顾问',
          cta:ctaEl?.value || ''
        }
      )
      renderReview(data.review || data)
      if(data.cover_result && typeof render === 'function'){
        render(data.cover_result)
      }
      if(typeof log === 'function') log(data)
    }catch(e){
      alert('无法通过审查：' + e.message)
      if(typeof log === 'function') log('无法通过审查：' + e.message)
    }
  }

  window.rejectVideoReview = async function(){
    const jobId = reviewJobId()
    if(!jobId) return
    const reason = prompt('填写退回原因', '字幕或画面仍需修改')
    if(reason === null) return
    try{
      const data = await reviewFetch(
        `/api/video/review/${encodeURIComponent(jobId)}/reject`,
        {reviewer:'human', reason}
      )
      renderReview(data)
      if(typeof log === 'function') log(data)
    }catch(e){
      alert('退回失败：' + e.message)
    }
  }

  window.addEventListener('DOMContentLoaded', function(){
    ensurePanel()
    setPackagingEnabled(false)

    if(typeof window.loadLatest === 'function'){
      const originalLoadLatest = window.loadLatest
      window.loadLatest = async function(){
        const result = await originalLoadLatest.apply(this, arguments)
        await window.refreshVideoReview()
        return result
      }
    }

    const jobInput = document.getElementById('jobId')
    if(jobInput){
      jobInput.addEventListener('change', window.refreshVideoReview)
      if(jobInput.value.trim()) window.refreshVideoReview()
    }
  })
})()
</script>
<!-- AI_VIDEO_REVIEW_GATE_UI_END -->
'''


def patch(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"target not found: {path}")

    text = path.read_text(encoding="utf-8")
    text = re.sub(
        re.escape(START) + r".*?" + re.escape(END),
        "",
        text,
        flags=re.S,
    )

    marker = "<!-- AI_VIDEO_GRAPHIC_WINDOW_STANDALONE_V2_NO_IFRAME -->"
    if marker in text:
        text = text.replace(marker, BLOCK + "\n" + marker, 1)
    elif "</body>" in text:
        text = text.replace("</body>", BLOCK + "\n</body>", 1)
    else:
        text += "\n" + BLOCK

    path.write_text(text, encoding="utf-8")
    print(f"patched review gate UI: {path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: patch_graphic_window_review_gate.py <index.html> [...]")
    for raw in sys.argv[1:]:
        patch(Path(raw))
