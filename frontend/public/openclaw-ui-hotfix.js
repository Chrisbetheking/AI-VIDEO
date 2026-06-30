(function () {
  const API_BASE = "https://ai-video.47-76-143-158.sslip.io";

  const replacements = [
    ["流量监控与投流决策", "发布后数据复盘与投放建议"],
    ["生成投流决策", "生成投放建议"],
    ["系统会用规则 + AI 判断是否加热、换封面、重剪或停投。", "未接入抖音开放平台 API：这里只基于人工录入/公开可见数据做复盘建议，不读取投流后台。"],
    ["投流分", "建议分"],
    ["投流消耗", "已花费预算"],
    ["预算建议：0（暂不投入、待完善素材）", "建议：暂不投放，先补标题、封面、口播钩子和基础数据。"],
    ["这里不是手工记录本，而是自动采集的账号池。系统会按账号库顺序抓近期视频、归类同行内容、学习钩子结构。", "这里联动 OpenClaw 自动发现和初筛竞品账号。系统每天自动扩展新账号、去重、打分；人工只负责复核和跟进。"],
    ["刷新账号库", "同步 OpenClaw 账号池"],
    ["采集全部账号", "OpenClaw 自动找新账号"],
    ["加入账号库", "手动补充种子账号"],
    ["worker 状态", "OpenClaw 状态"],
    ["本轮采集失败", "等待 OpenClaw 自动发现 / 初筛"],
    ["获客自动化", "OpenClaw 获客自动化"],
    ["抖音截留获客", "OpenClaw 截流线索发现"],
    ["博主联动流量", "同行账号扩展"],
    ["采集目标客户", "自动发现线索"],
    ["自动监听", "自动监听线索"],
    ["自动回复", "生成回复草稿"],
    ["目标用户导流私域", "飞书/微信通知人工承接"],
    ["私信咨询 / 需求筛选 / 加微信进入私域 / 预约顾问沟通", "OpenClaw 初筛线索 → 飞书/微信提醒 → 人工确认 → 私域承接"],
    ["自动回复模板 → 私信筛选 → 微信私域标签", "回复草稿 → 人工确认 → 微信/飞书标签"],
  ];

  function esc(s) {
    return String(s || "").replace(/[&<>"']/g, m => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[m]));
  }

  async function j(url, opts) {
    const r = await fetch(url, opts || {});
    return await r.json();
  }

  function walkText(node) {
    if (!node) return;
    if (node.nodeType === Node.TEXT_NODE) {
      let text = node.nodeValue || "";
      let changed = false;
      for (const [a, b] of replacements) {
        if (text.includes(a)) {
          text = text.split(a).join(b);
          changed = true;
        }
      }
      if (changed) node.nodeValue = text;
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    if (["SCRIPT", "STYLE", "TEXTAREA", "INPUT"].includes(node.tagName)) return;
    for (const child of Array.from(node.childNodes)) walkText(child);
  }

  function hideOpsShooting() {
    for (const el of Array.from(document.querySelectorAll("body *"))) {
      const t = (el.innerText || "").trim();
      if (t === "运营拍摄" || t.includes("运营拍摄")) {
        const item = el.closest("a,button,li,[role='button']") || el;
        if (item && item !== document.body) item.style.display = "none";
      }
    }
  }

  function setLocalStatus(url, status) {
    const key = "openclaw_status_" + url;
    localStorage.setItem(key, status);
  }

  function getLocalStatus(url) {
    return localStorage.getItem("openclaw_status_" + url) || "待处理";
  }

  async function loadOpenClawData() {
    const [health, accounts, videos] = await Promise.all([
      j(API_BASE + "/api/openclaw/health").catch(e => ({ ok:false, error:e.message })),
      j(API_BASE + "/api/openclaw/accounts").catch(e => ({ ok:false, accounts:[], error:e.message })),
      j(API_BASE + "/api/openclaw/videos").catch(e => ({ ok:false, videos:[], error:e.message })),
    ]);

    return {
      health,
      accounts: accounts.accounts || [],
      videos: videos.videos || [],
    };
  }

  async function triggerDiscovery() {
    return await j(API_BASE + "/api/openclaw/discovery/start", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
    });
  }

  async function triggerFallbackCollect() {
    return await j(API_BASE + "/api/openclaw/fallback/run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        dry_run: true,
        force_openclaw: true,
        title: "前端触发 OpenClaw 采集",
        keywords: ["马来西亚房产","马来西亚买房","吉隆坡房产","槟城房产","柔佛房产","MM2H","马来西亚第二家园","海外置业 马来西亚","大马房产","大马买房"]
      })
    });
  }

  function shouldShowPanel() {
    const t = document.body.innerText || "";
    return (
      t.includes("竞品账号库") ||
      t.includes("同行采集") ||
      t.includes("获客自动化") ||
      t.includes("OpenClaw") ||
      t.includes("账号库")
    );
  }

  function renderOpenClawPanelShell() {
    if (!shouldShowPanel()) return null;
    let box = document.getElementById("openclaw-ui-bridge");
    if (box) return box;

    const main = document.querySelector("main") || document.body;
    box = document.createElement("div");
    box.id = "openclaw-ui-bridge";
    box.style.cssText = `
      margin: 16px 0 22px;
      padding: 18px 20px;
      border: 1px solid #bcd3ff;
      border-radius: 18px;
      background: linear-gradient(135deg, #f7fbff, #eef4ff);
      box-shadow: 0 10px 28px rgba(37, 99, 235, .08);
      font-family: -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
      color:#0f172a;
    `;
    main.prepend(box);
    return box;
  }

  function renderStatusButtons(url) {
    const current = getLocalStatus(url);
    const options = ["待处理", "已联系", "已加微信", "无效"];
    return `
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;">
        ${options.map(x => `
          <button data-openclaw-status="${esc(x)}" data-openclaw-url="${esc(url)}"
            style="border:1px solid ${current === x ? "#3157ff" : "#cbd5e1"};
            background:${current === x ? "#3157ff" : "white"};
            color:${current === x ? "white" : "#334155"};
            border-radius:999px;padding:5px 9px;font-size:12px;cursor:pointer;">
            ${esc(x)}
          </button>
        `).join("")}
      </div>
    `;
  }

  function accountRow(a) {
    const url = a.account_url || "";
    return `
      <div style="padding:13px;border:1px solid #dbeafe;border-radius:14px;background:white;">
        <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;">
          <div>
            <div style="font-weight:800;font-size:15px;">${esc(a.account_name || "OpenClaw发现账号")}</div>
            <div style="font-size:12px;color:#64748b;margin-top:4px;">${esc(a.keyword || "")} · ${esc(a.source || "")}</div>
          </div>
          <div style="font-size:18px;font-weight:900;color:#3157ff;">${esc(a.score || 0)}</div>
        </div>
        <div style="font-size:12px;color:#475569;margin-top:8px;word-break:break-all;">
          <a href="${esc(url)}" target="_blank" style="color:#2563eb;">打开账号</a>
          <span style="color:#94a3b8;"> ${esc(url)}</span>
        </div>
        ${renderStatusButtons(url)}
      </div>
    `;
  }

  function videoRow(v) {
    const url = v.video_url || "";
    return `
      <div style="padding:13px;border:1px solid #e0e7ff;border-radius:14px;background:white;">
        <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;">
          <div>
            <div style="font-weight:800;font-size:15px;">${esc(v.video_title || "候选视频")}</div>
            <div style="font-size:12px;color:#64748b;margin-top:4px;">${esc(v.account_name || "")} · ${esc(v.source || "")}</div>
          </div>
          <div style="font-size:18px;font-weight:900;color:#3157ff;">${esc(v.score || 0)}</div>
        </div>
        <div style="font-size:12px;color:#475569;margin-top:8px;word-break:break-all;">
          <a href="${esc(url)}" target="_blank" style="color:#2563eb;">打开视频</a>
          <span style="color:#94a3b8;"> ${esc(url)}</span>
        </div>
      </div>
    `;
  }

  async function refreshOpenClawPanel() {
    const box = renderOpenClawPanelShell();
    if (!box) return;

    box.innerHTML = `
      <div style="font-size:20px;font-weight:900;margin-bottom:8px;">OpenClaw 自动采集与获客联动</div>
      <div style="font-size:14px;color:#475569;line-height:1.7;margin-bottom:14px;">
        正在读取 OpenClaw 账号池和视频池……
      </div>
    `;

    let data;
    try {
      data = await loadOpenClawData();
    } catch (e) {
      box.innerHTML = `<div style="color:#b91c1c;font-weight:800;">OpenClaw 数据读取失败：${esc(e.message)}</div>`;
      return;
    }

    const accounts = data.accounts || [];
    const videos = data.videos || [];
    const active = data.health && data.health.ok;

    box.innerHTML = `
      <div style="display:flex;justify-content:space-between;gap:14px;align-items:flex-start;flex-wrap:wrap;">
        <div>
          <div style="font-size:20px;font-weight:900;margin-bottom:8px;">OpenClaw 自动采集与获客联动</div>
          <div style="font-size:14px;color:#475569;line-height:1.7;">
            当前模式：OpenClaw 自动找新账号、初筛竞品内容、沉淀账号池/视频池；不自动出片、不自动骚扰用户。
            飞书/微信通知为待接入，当前先由页面展示给人工处理。
          </div>
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          <button id="openclaw-discovery-btn" style="border:0;background:#3157ff;color:white;border-radius:12px;padding:11px 16px;font-weight:800;cursor:pointer;">OpenClaw 自动找号</button>
          <button id="openclaw-refresh-btn" style="border:1px solid #bcd3ff;background:white;color:#3157ff;border-radius:12px;padding:10px 16px;font-weight:800;cursor:pointer;">刷新账号池</button>
          <a href="${API_BASE}/openclaw-dashboard" target="_blank" style="background:white;color:#3157ff;border:1px solid #bcd3ff;border-radius:12px;padding:10px 16px;font-weight:800;text-decoration:none;">采集面板</a>
          <a href="${API_BASE}/api/openclaw/export.csv" target="_blank" style="background:white;color:#3157ff;border:1px solid #bcd3ff;border-radius:12px;padding:10px 16px;font-weight:800;text-decoration:none;">导出CSV</a>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:16px;">
        <div style="background:white;border:1px solid #dbeafe;border-radius:14px;padding:13px;">
          <div style="font-size:12px;color:#64748b;">OpenClaw 状态</div>
          <div style="font-size:22px;font-weight:900;color:${active ? "#16a34a" : "#dc2626"};">${active ? "running" : "offline"}</div>
        </div>
        <div style="background:white;border:1px solid #dbeafe;border-radius:14px;padding:13px;">
          <div style="font-size:12px;color:#64748b;">账号池</div>
          <div style="font-size:22px;font-weight:900;">${accounts.length}</div>
        </div>
        <div style="background:white;border:1px solid #dbeafe;border-radius:14px;padding:13px;">
          <div style="font-size:12px;color:#64748b;">视频池</div>
          <div style="font-size:22px;font-weight:900;">${videos.length}</div>
        </div>
        <div style="background:white;border:1px solid #dbeafe;border-radius:14px;padding:13px;">
          <div style="font-size:12px;color:#64748b;">飞书/微信</div>
          <div style="font-size:22px;font-weight:900;color:#f97316;">待接入</div>
        </div>
      </div>

      <div id="openclaw-bridge-status" style="font-size:13px;color:#64748b;margin-top:12px;">
        流程：OpenClaw 初筛 → 页面展示 → 人工确认 → 飞书/微信待接入 → 私域承接。
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px;">
        <div>
          <div style="font-size:16px;font-weight:900;margin-bottom:10px;">账号候选 Top 10</div>
          <div style="display:grid;gap:10px;">
            ${accounts.slice(0, 10).map(accountRow).join("") || `<div style="color:#64748b;">暂无账号，点击 OpenClaw 自动找号。</div>`}
          </div>
        </div>
        <div>
          <div style="font-size:16px;font-weight:900;margin-bottom:10px;">视频候选 Top 10</div>
          <div style="display:grid;gap:10px;">
            ${videos.slice(0, 10).map(videoRow).join("") || `<div style="color:#64748b;">暂无视频候选。</div>`}
          </div>
        </div>
      </div>
    `;

    document.getElementById("openclaw-refresh-btn").onclick = refreshOpenClawPanel;

    document.getElementById("openclaw-discovery-btn").onclick = async function () {
      const btn = this;
      const status = document.getElementById("openclaw-bridge-status");
      btn.disabled = true;
      btn.innerText = "OpenClaw 正在找号...";
      status.innerText = "状态：已提交 OpenClaw 自动账号发现任务，后台会运行几分钟，不会自动出片。";

      try {
        const res = await triggerDiscovery();
        status.innerText = "状态：OpenClaw 自动找号任务已提交：" + JSON.stringify(res);
        await triggerFallbackCollect().catch(() => null);
        setTimeout(refreshOpenClawPanel, 15000);
      } catch (e) {
        status.innerText = "状态：提交失败：" + e.message;
        btn.disabled = false;
        btn.innerText = "OpenClaw 自动找号";
      }
    };

    for (const btn of Array.from(box.querySelectorAll("[data-openclaw-status]"))) {
      btn.onclick = function () {
        setLocalStatus(this.getAttribute("data-openclaw-url"), this.getAttribute("data-openclaw-status"));
        refreshOpenClawPanel();
      };
    }
  }

  function patchButtons() {
    for (const btn of Array.from(document.querySelectorAll("button"))) {
      const t = (btn.innerText || "").trim();
      if (["采集全部账号", "一键采集全部账号", "开始采集", "OpenClaw 自动找新账号"].some(x => t.includes(x))) {
        btn.onclick = async function (e) {
          e.preventDefault();
          e.stopPropagation();
          const old = btn.innerText;
          btn.disabled = true;
          btn.innerText = "OpenClaw 提交中...";
          try {
            const res = await triggerDiscovery();
            alert("OpenClaw 自动找号已提交：\n" + JSON.stringify(res, null, 2));
            btn.innerText = "已提交 OpenClaw";
            setTimeout(refreshOpenClawPanel, 15000);
          } catch (err) {
            alert("OpenClaw 提交失败：" + err.message);
            btn.disabled = false;
            btn.innerText = old;
          }
        };
      }
    }
  }

  function runBasePatch() {
    walkText(document.body);
    hideOpsShooting();
    patchButtons();
  }

  let lastPath = "";
  function loop() {
    runBasePatch();
    if (location.pathname !== lastPath || shouldShowPanel()) {
      lastPath = location.pathname;
      refreshOpenClawPanel();
    }
  }

  setInterval(loop, 1500);
  window.addEventListener("load", loop);
})();
