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

import os
import subprocess
import sys
import time
from typing import Any

import httpx
from dotenv import load_dotenv


def api_base() -> str:
    v = os.getenv('API_BASE_URL', '').rstrip('/')
    if not v:
        raise RuntimeError('缺少 API_BASE_URL')
    return v


def token() -> str:
    v = os.getenv('HEAT_RADAR_INGEST_TOKEN', '')
    if not v:
        raise RuntimeError('缺少 HEAT_RADAR_INGEST_TOKEN')
    return v


def fetch_next() -> dict[str, Any] | None:
    with httpx.Client(timeout=60) as client:
        res = client.get(f'{api_base()}/api/collector/commands/next', params={'token': token()})
        res.raise_for_status()
        data = res.json()
        return data.get('command')


def complete(command_id: str, status: str, message: str = '') -> None:
    with httpx.Client(timeout=60) as client:
        client.post(f'{api_base()}/api/collector/commands/{command_id}/complete', json={'token': token(), 'status': status, 'message': message})


def run_command(cmd: dict[str, Any]) -> int:
    args = [sys.executable, 'run_all.py']
    if cmd.get('headful', True):
        args.append('--headful')
    else:
        args.append('--headless')
    if cmd.get('dry_run'):
        args.append('--dry-run')
    limit = int(cmd.get('limit') or 1)
    args += ['--limit', str(limit)]
    account = str(cmd.get('account') or '').strip()
    if account:
        args += ['--account', account]
    if cmd.get('no_delay') or limit <= 3:
        args.append('--no-delay')
    print('执行主网站命令：', ' '.join(args))
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    env['COLLECTOR_COMMAND_ID'] = str(cmd.get('command_id') or cmd.get('id') or '')
    return subprocess.call(args, env=env)


def main() -> None:
    load_dotenv()
    once = '--once' in sys.argv
    interval = int(os.getenv('COMMAND_POLL_INTERVAL_SECONDS', '5'))
    print(f'ECS 命令监听启动。每 {interval} 秒检查主网站采集命令。全自动模式：按网页填写账号数执行；3个以内默认快速不等待；遇到验证记录并跳过。')
    while True:
        try:
            cmd = fetch_next()
            if cmd:
                cid = str(cmd.get('command_id') or cmd.get('id') or '')
                code = run_command(cmd)
                complete(cid, 'finished' if code == 0 else 'failed', f'退出码 {code}')
            elif once:
                print('没有待执行命令。')
                return
        except Exception as exc:
            print(f'命令监听错误：{type(exc).__name__}: {exc}')
            if once:
                raise
        time.sleep(interval)


if __name__ == '__main__':
    main()
