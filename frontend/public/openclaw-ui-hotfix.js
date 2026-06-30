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

  function walkText(node) {
    if (!node) return;
    if (node.nodeType === Node.TEXT_NODE) {
      let text = node.nodeValue;
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
    const all = Array.from(document.querySelectorAll("body *"));
    for (const el of all) {
      const t = (el.innerText || "").trim();
      if (t === "运营拍摄" || t.includes("运营拍摄")) {
        const item = el.closest("button,a,li,[role='button'],.card,div");
        if (item && item !== document.body) {
          item.style.display = "none";
        }
      }
    }
  }

  async function triggerOpenClaw() {
    const payload = {
      dry_run: true,
      force_openclaw: true,
      title: "前端触发 OpenClaw 自动找号",
      keywords: [
        "马来西亚房产",
        "马来西亚买房",
        "吉隆坡房产",
        "槟城房产",
        "柔佛房产",
        "MM2H",
        "马来西亚第二家园",
        "海外置业 马来西亚",
        "大马房产",
        "大马买房"
      ]
    };

    const r = await fetch(API_BASE + "/api/openclaw/fallback/run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });

    return await r.json();
  }

  function addOpenClawPanel() {
    const bodyText = document.body.innerText || "";
    const shouldShow =
      bodyText.includes("竞品账号库") ||
      bodyText.includes("同行采集") ||
      bodyText.includes("OpenClaw 获客自动化") ||
      bodyText.includes("获客自动化");

    if (!shouldShow) return;
    if (document.getElementById("openclaw-ui-bridge")) return;

    const main = document.querySelector("main") || document.body;

    const box = document.createElement("div");
    box.id = "openclaw-ui-bridge";
    box.style.cssText = `
      margin: 16px 0;
      padding: 18px 20px;
      border: 1px solid #bcd3ff;
      border-radius: 18px;
      background: linear-gradient(135deg, #f7fbff, #eef4ff);
      box-shadow: 0 10px 28px rgba(37, 99, 235, .08);
      font-family: -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
    `;

    box.innerHTML = `
      <div style="font-size:20px;font-weight:800;color:#0f172a;margin-bottom:8px;">
        OpenClaw 自动采集与获客联动
      </div>
      <div style="font-size:14px;color:#475569;line-height:1.7;margin-bottom:14px;">
        当前模式：OpenClaw 自动找新账号、初筛竞品内容、沉淀账号池/视频池；不自动出片、不自动骚扰用户。
        下一步可接入飞书或微信，把高分线索推给人工处理。
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;">
        <button id="openclaw-trigger-btn" style="border:0;background:#3157ff;color:white;border-radius:12px;padding:11px 16px;font-weight:700;cursor:pointer;">
          OpenClaw 自动找号
        </button>
        <a href="${API_BASE}/openclaw-dashboard" target="_blank" style="background:white;color:#3157ff;border:1px solid #bcd3ff;border-radius:12px;padding:10px 16px;font-weight:700;text-decoration:none;">
          打开采集面板
        </a>
        <a href="${API_BASE}/api/openclaw/export.csv" target="_blank" style="background:white;color:#3157ff;border:1px solid #bcd3ff;border-radius:12px;padding:10px 16px;font-weight:700;text-decoration:none;">
          导出候选 CSV
        </a>
      </div>
      <div id="openclaw-bridge-status" style="font-size:13px;color:#64748b;">
        状态：等待操作。流程为 OpenClaw 初筛 → 飞书/微信通知待接入 → 人工确认 → 私域承接。
      </div>
    `;

    main.prepend(box);

    const btn = document.getElementById("openclaw-trigger-btn");
    const status = document.getElementById("openclaw-bridge-status");

    btn.onclick = async function () {
      btn.disabled = true;
      btn.innerText = "正在提交...";
      status.innerText = "状态：正在触发 OpenClaw 自动找号，不会自动出片。";

      try {
        const res = await triggerOpenClaw();
        status.innerText = "状态：已提交 OpenClaw 任务：" + JSON.stringify(res);
        btn.innerText = "已提交，稍后刷新";
      } catch (e) {
        status.innerText = "状态：提交失败：" + e.message;
        btn.innerText = "重新触发";
        btn.disabled = false;
      }
    };
  }

  function patchButtons() {
    const buttons = Array.from(document.querySelectorAll("button"));
    for (const btn of buttons) {
      const t = (btn.innerText || "").trim();

      if (["采集全部账号", "一键采集全部账号", "开始采集"].some(x => t.includes(x))) {
        btn.onclick = async function (e) {
          e.preventDefault();
          e.stopPropagation();
          btn.disabled = true;
          const old = btn.innerText;
          btn.innerText = "OpenClaw 提交中...";
          try {
            const res = await triggerOpenClaw();
            alert("OpenClaw 已开始自动找号/采集：\n" + JSON.stringify(res, null, 2));
            btn.innerText = "已提交 OpenClaw";
          } catch (err) {
            alert("OpenClaw 提交失败：" + err.message);
            btn.disabled = false;
            btn.innerText = old;
          }
        };
      }
    }
  }

  function run() {
    walkText(document.body);
    hideOpsShooting();
    addOpenClawPanel();
    patchButtons();
  }

  setInterval(run, 900);
  window.addEventListener("load", run);
})();
