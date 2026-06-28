# AGENTS.md - Codex Development Rules for AI Video Growth Studio

## Core Rules

1. **Never commit `.env` files.** No API keys, tokens, cookies, or server passwords in git.
2. **Never commit media files.** No `.mp4`, `.mov`, `.mkv`, `.webm`, `.mp3`, `.wav` in git.
3. **Never commit databases.** No `.db`, `.sqlite3`, `.sqlite` files.
4. **Never push directly to `main`.** All changes go through feature/fix branches.
5. **Run tests after every change.** At minimum: `python -m py_compile` on modified files.
6. **Analyze the call chain before large changes.** Read the affected endpoint, service, and schema first.
7. **Do not append temporary patches at file ends.** Integrate fixes properly into existing logic.

## Development Workflow

```bash
# 1. Create a fix branch
git checkout -b fix/descriptive-name

# 2. Make changes, then verify
cd backend
python -m py_compile app/main.py app/services/video.py app/services/video_edit.py

# 3. Run tests
pytest

# 4. Check git status - ensure no .env, media, db, or logs staged
git status

# 5. Commit and push to the branch (NOT main)
git add <changed files>
git commit -m "Fix: descriptive message"
git push -u origin fix/descriptive-name
```

## Project Structure

- `backend/app/main.py` - FastAPI routes (monolithic, 2000+ lines)
- `backend/app/services/` - Business logic services
- `backend/app/schemas.py` - Pydantic request/response models
- `frontend/src/App.tsx` - React frontend (monolithic, 3000+ lines)
- `frontend/src/api.ts` - API client

## Key Call Chains

- **Compose**: `/api/compose-video` → `video.py:compose_video()` → `synthesize_segmented_audio()` → `create_smart_ass()` → `build_video_base()` → `burn_ass_and_audio()`
- **TTS**: `/api/tts-segments` → `tts.py:synthesize_tts_segments()`
- **Digital Human**: `/api/digital-human/create` → `digital_human.py:call_jimeng_digital_human()` / `call_fal_lipsync()`

## Critical Constraints

- **Subtitle font**: < 70 falls back to 80. No black box, no BackColour, no drawtext box=1.
- **Duration**: Final video follows audio length, not asset total duration.
- **Digital human**: Uses hook_text (first sentence, 18-24 chars), not full script.
- **Keywords**: Pure text overlays with outline + shadow, no rectangle backgrounds.
