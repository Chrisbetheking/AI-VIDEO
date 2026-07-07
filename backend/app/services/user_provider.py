from __future__ import annotations

import os
import sqlite3
import secrets
from pathlib import Path
from typing import Optional

BASE_DIR = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
DB_PATH = BASE_DIR / "data" / "users.sqlite3"

def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = _conn()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        api_key TEXT UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

def create_user() -> dict:
    user_id = secrets.token_hex(8)
    api_key = secrets.token_urlsafe(32)

    conn = _conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (user_id, api_key) VALUES (?, ?)",
        (user_id, api_key),
    )
    conn.commit()
    conn.close()

    return {"user_id": user_id, "api_key": api_key}

def get_user_by_key(api_key: str) -> Optional[str]:
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE api_key = ?", (api_key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None
