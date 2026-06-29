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
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from collector import run_collector
from state import SingleRunLock
from uploader import upload_excel, start_remote_run, report_event


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--headful", action="store_true", help="显示浏览器，适合第一次登录")
    parser.add_argument("--headless", action="store_true", help="无头运行")
    parser.add_argument("--dry-run", action="store_true", help="只生成 Excel 和输出 JSON，不上传")
    parser.add_argument("--accounts", default="accounts.seed.json")
    parser.add_argument("--include-seen", action="store_true", help="即使视频已采过也重新导出")
    parser.add_argument("--once", action="store_true", help="只采 1 个账号，适合临时测试")
    parser.add_argument("--limit", type=int, default=0, help="本轮采集账号数量，例如 --limit 5")
    parser.add_argument("--account", default="", help="只采集账号名/链接包含该关键词的账号")
    parser.add_argument("--no-delay", action="store_true", help="本轮账号之间不等待，仅用于测试")
    parser.add_argument("--manual-login", action="store_true", help="调试用：遇到登录/验证时暂停，等人工处理后按回车继续。默认全自动跳过，不等待。")
    args = parser.parse_args()
    if not args.headful and not args.headless:
        args.headless = os.getenv("HEADLESS", "false").lower() == "true"
    if args.headful:
        args.headless = False
    with SingleRunLock(os.getenv("LOCK_FILE", "collector.lock")):
        try:
            total = 1 if args.once else (args.limit or int(os.getenv("BATCH_ACCOUNT_LIMIT", "1")))
            start_remote_run(total_accounts=total, dry_run=args.dry_run, mode="ecs_worker", command_id=os.getenv("COLLECTOR_COMMAND_ID", ""), message=f"ECS 采集器启动：本轮 {total} 个账号{'，快速模式不等待' if args.no_delay else ''}")
        except Exception as exc:
            print(f"主网站采集进度初始化失败，但继续本地采集：{exc}")
        try:
            excel_path: Path = asyncio.run(run_collector(args))
            if os.getenv("IMMEDIATE_VIDEO_INTAKE", "true").lower() in {"0", "false", "no", "off"}:
                upload_excel(excel_path, dry_run=args.dry_run)
            else:
                print("IMMEDIATE_VIDEO_INTAKE=true：采集过程中已按账号即时提交，跳过最终整批重复上传。")
            report_event("run_finished", "本轮采集完成", progress={"completed_accounts": total})
        except Exception as exc:
            report_event("run_failed", "本轮采集失败", level="error", error_detail=str(exc))
            raise


if __name__ == "__main__":
    main()
