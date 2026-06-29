from __future__ import annotations


def _force_safe_console() -> None:
    import os as _os
    import sys as _sys
    _os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    for _stream in (_sys.stdout, _sys.stderr):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

_force_safe_console()

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from excel_io import excel_rows_to_accounts, read_excel_rows
from utils import split_tags


def build_payload(accounts: list[dict[str, Any]], run_id: str | None = None) -> dict[str, Any]:
    load_dotenv()
    keywords = split_tags(os.getenv("KEYWORDS", "马来西亚房产,第二家园,海外置业,马来西亚生活"))
    return {
        "token": os.getenv("HEAT_RADAR_INGEST_TOKEN", ""),
        "source_name": "local_douyin_excel_worker",
        "run_id": run_id or f"douyin_local_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "keywords": keywords,
        "save_to_memory": True,
        "auto_add_accounts": False,
        "auto_accept_min_score": int(os.getenv("AUTO_ACCEPT_MIN_SCORE", "72")),
        "max_stale_days": int(os.getenv("MAX_STALE_DAYS", "90")),
        "accounts": accounts,
        "items": [],
    }


def _api_base() -> str:
    api_base = os.getenv("API_BASE_URL", "").rstrip("/")
    if not api_base:
        raise RuntimeError("缺少 API_BASE_URL，请在 .env 里配置后端地址")
    return api_base


def _token() -> str:
    token = os.getenv("HEAT_RADAR_INGEST_TOKEN", "")
    if not token:
        raise RuntimeError("缺少 HEAT_RADAR_INGEST_TOKEN，请在 .env 里配置上传 token")
    return token




def _collector_run_id() -> str:
    return os.getenv("COLLECTOR_RUN_ID", "").strip()


def start_remote_run(*, total_accounts: int = 0, dry_run: bool = False, mode: str = "ecs_worker", command_id: str = "", message: str = "") -> dict[str, Any]:
    """Create a visible run record on the main website."""
    url = f"{_api_base()}/api/collector/runs/start"
    payload = {
        "token": _token(),
        "total_accounts": total_accounts,
        "dry_run": dry_run,
        "mode": mode,
        "command_id": command_id,
        "message": message or "ECS 采集器启动",
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, json=payload)
        if resp.status_code >= 400:
            print("采集进度初始化失败：", resp.text[:800])
            resp.raise_for_status()
        data = resp.json()
    run_id = str(data.get("run_id") or data.get("id") or "")
    if run_id:
        os.environ["COLLECTOR_RUN_ID"] = run_id
    return data


def report_event(stage: str, message: str = "", *, level: str = "info", account_name: str = "", account_url: str = "", video_title: str = "", video_url: str = "", progress: dict[str, Any] | None = None, error_detail: str = "", raw: dict[str, Any] | None = None) -> None:
    """Push one progress event to the main website. Failure never stops crawling."""
    run_id = _collector_run_id()
    if not run_id:
        return
    try:
        url = f"{_api_base()}/api/collector/runs/{run_id}/event"
        payload = {
            "token": _token(),
            "stage": stage,
            "level": level,
            "message": message,
            "account_name": account_name,
            "account_url": account_url,
            "video_title": video_title,
            "video_url": video_url,
            "progress": progress or {},
            "error_detail": error_detail,
            "raw": raw or {},
        }
        with httpx.Client(timeout=30) as client:
            client.post(url, json=payload)
    except Exception as exc:
        print(f"进度上报失败：{type(exc).__name__}: {exc}")

def upload_payload(payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_api_base()}/api/heat-radar/openclaw/ingest"
    with httpx.Client(timeout=120) as client:
        resp = client.post(url, json=payload)
        if resp.status_code >= 400:
            print("上传失败，后端返回：")
            print(resp.text[:2000])
            resp.raise_for_status()
        return resp.json()


def _video_intake_payload(account: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    return {
        "token": _token(),
        "account_name": account.get("name") or item.get("account_name") or "未命名账号",
        "account_url": account.get("url") or item.get("account_url") or "",
        "platform": account.get("platform") or item.get("platform") or "抖音",
        "video_url": item.get("url") or item.get("video_url") or "",
        "resolved_video_url": item.get("resolved_video_url") or item.get("video_play_url") or "",
        "analysis_mode": item.get("analysis_mode") or "text_fallback",
        "video_download_status": item.get("video_download_status") or "pending",
        "video_download_error": item.get("video_download_error") or "",
        "download_method": item.get("download_method") or "",
        "title": item.get("title") or item.get("video_title") or "",
        "published_at": item.get("published_at") or "",
        "is_pinned": bool(item.get("is_pinned")),
        "tags": item.get("tags") or account.get("tags") or [],
        "notes": "ECS 采集器提交：优先使用 resolved_video_url/后端采集器下载视频并调用豆包视频理解；失败则降级为文案/互动数据分析。",
        "like_count": int(item.get("like_count") or 0),
        "comment_count": int(item.get("comment_count") or 0),
        "favorite_count": int(item.get("favorite_count") or 0),
        "share_count": int(item.get("share_count") or 0),
        "view_count": int(item.get("view_count") or 0),
        "auto_save_review": True,
    }


def upload_video_intake(accounts: list[dict[str, Any]], dry_run: bool = False) -> dict[str, Any]:
    """逐条视频提交给主网站 /api/heat-radar/video-intake。

    主网站负责：下载视频 -> 上传 R2 -> 豆包视频理解 -> 强推理模型判断 -> 保存审核记录。
    """
    api_base = _api_base()
    url = f"{api_base}/api/heat-radar/video-intake"
    videos: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for account in accounts:
        for item in account.get("recent_items") or []:
            video_url = item.get("url") or item.get("video_url")
            if video_url:
                videos.append((account, item))

    if not videos:
        print("没有采到具体视频，不调用豆包分析接口。请先确认账号主页/视频链接正确，并完成登录/验证。")
        report_event("videos_empty", "本轮没有提取到具体视频：可能页面验证、账号无新内容或已全部采过。", level="warning", progress={"success_videos": 0, "failed_videos": 0})
        return {"ok": False, "sent": 0}

    print(f"准备提交 {len(videos)} 条视频到主网站 video-intake，由后端下载视频并调用豆包分析。")
    report_event("videos_found", f"采集到 {len(videos)} 条视频，开始提交主网站分析", progress={"success_videos": 0, "failed_videos": 0})
    results = []
    with httpx.Client(timeout=int(os.getenv("VIDEO_INTAKE_HTTP_TIMEOUT", "900"))) as client:
        for idx, (account, item) in enumerate(videos, start=1):
            payload = _video_intake_payload(account, item)
            print(f"[{idx}/{len(videos)}] 提交视频分析：{payload.get('title') or payload.get('video_url')}")
            report_event("video_submitting", "提交视频给主网站豆包分析", account_name=payload.get("account_name", ""), account_url=payload.get("account_url", ""), video_title=payload.get("title", ""), video_url=payload.get("video_url", ""), progress={"success_videos": idx - 1, "failed_videos": 0})
            if dry_run:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                report_event("video_extracted", f"已提取待分析视频：{payload.get('title') or payload.get('video_url')}", account_name=payload.get("account_name", ""), account_url=payload.get("account_url", ""), video_title=payload.get("title", ""), video_url=payload.get("video_url", ""), raw={"payload": payload}, progress={"success_videos": idx})
                results.append({"dry_run": True, "payload": payload})
                continue
            resp = client.post(url, json=payload)
            if resp.status_code >= 400:
                print("视频分析接口返回错误：")
                print(resp.text[:2000])
                results.append({"ok": False, "status_code": resp.status_code, "text": resp.text[:500]})
                report_event("video_failed", f"视频分析接口失败：{resp.status_code}", level="error", account_name=payload.get("account_name", ""), account_url=payload.get("account_url", ""), video_title=payload.get("title", ""), video_url=payload.get("video_url", ""), error_detail=resp.text[:1000], progress={"failed_videos": 1})
                if "HEAT_RADAR_INGEST_TOKEN" in resp.text or resp.status_code in {401, 403}:
                    print("检测到 token 不匹配：请把 Render 环境变量 HEAT_RADAR_INGEST_TOKEN 和 ECS .env 里的值改成完全一致，然后重启/重新部署 Render 后端。")
                    break
                continue
            data = resp.json()
            print(f"  ok={data.get('ok')} r2={data.get('r2_video_url') or ''} mode={data.get('analysis_mode') or ''}")
            r = data.get("review") or {}
            decision = str(r.get("decision") or data.get("decision") or "").lower()
            score = r.get("score", data.get("score", ""))
            reason = str(r.get("reason") or data.get("reason") or data.get("summary") or "")[:180]
            warnings = data.get("warnings") if isinstance(data.get("warnings"), list) else []
            if decision in {"keep", "accept", "accepted", "save", "hot"} or (isinstance(score, (int, float)) and score >= int(os.getenv("AUTO_ACCEPT_MIN_SCORE", "72"))):
                stage = "video_selected"
                msg = f"入选：{payload.get('title') or payload.get('video_url')}｜{score}分｜{reason or '达到客户意图/马来西亚方向要求'}"
            elif decision in {"archive", "reject", "skip", "low_value"}:
                stage = "video_archived"
                msg = f"未入选：{payload.get('title') or payload.get('video_url')}｜{score}分｜{reason or '相关性或客户价值不足'}"
            else:
                stage = "video_analyzed"
                msg = f"已分析：{payload.get('title') or payload.get('video_url')}｜{score}分｜{reason or '等待后端返回入选结论'}"
            report_event(stage, msg, account_name=payload.get("account_name", ""), account_url=payload.get("account_url", ""), video_title=payload.get("title", ""), video_url=payload.get("video_url", ""), raw={"response": data, "review": r, "warnings": warnings}, progress={"success_videos": idx})
            if r:
                print(f"  AI判断：{r.get('decision')} / {r.get('score')} / {str(r.get('reason', ''))[:80]}")
            if warnings:
                print("  warnings:", " | ".join(map(str, warnings[:3])))
            results.append(data)
    return {"ok": True, "sent": len(videos), "results": results}


def upload_excel(path: str | Path, dry_run: bool = False) -> dict[str, Any]:
    load_dotenv()
    rows = read_excel_rows(path)
    accounts = excel_rows_to_accounts(rows)
    has_real_video = any((a.get("recent_items") or []) for a in accounts)
    if not has_real_video:
        print("没有采到具体视频，本轮只生成 Excel，不上传后端。请先完成登录/验证，或检查账号主页/视频链接。")
        payload = build_payload(accounts)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return payload

    # 默认走视频理解链路：主网站下载视频 -> 豆包分析 -> 强推理审核。
    if os.getenv("UPLOAD_MODE", "video_intake").lower() == "video_intake":
        return upload_video_intake(accounts, dry_run=dry_run)

    payload = build_payload(accounts)
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return payload
    result = upload_payload(payload)
    print("上传完成：")
    for key in ["received_accounts", "received_items", "saved_accounts", "saved_items", "accepted_accounts", "watch_accounts", "rejected_accounts", "archived_accounts"]:
        if key in result:
            print(f"- {key}: {result[key]}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Excel 文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只输出 JSON，不上传")
    args = parser.parse_args()
    upload_excel(args.file, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
