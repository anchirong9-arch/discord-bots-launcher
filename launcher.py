#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
백수톡 디코봇 런처 (discord-bots-launcher)
------------------------------------------
치현 님 PC에서 디스코드 봇 두 개를 한 번에 켜고 끕니다.

    료그봇   tools/log-bot     백수톡의 사진·삭제·입퇴장·음성 로그 -> paranoia #백수톡-로그
    뮤직봇   tools/music-bot   음성 채널에서 유튜브 곡 재생 (/r · /s · /q · /x)
    상태판   http://127.0.0.1:8771/   두 봇의 온라인/오프라인 확인 + 켜기/끄기 + 토큰 넣기

동작 방식
  * 실행하기.bat 은 pythonw.exe 로 이 파일을 띄웁니다. 까만 콘솔 창은 남지 않습니다.
  * 봇은 CREATE_NO_WINDOW 백그라운드 프로세스로 돌고, 로그는 logs/<봇>.log 에 쌓입니다.
  * .env 가 아직 없으면 에러로 죽지 않고 '토큰 미설정' 상태만 보여 줍니다.
  * 실행할 때 GitHub 의 version.json 을 3초만 확인해 새 버전이 있으면 ZIP 을 받아
    이 폴더를 덮어쓰고 새 코드로 다시 시작합니다. (.env·로그·bin·cookies.txt 는 절대 보존)
  * 이 창(상태판)을 닫아도 봇은 계속 돕니다. 끄는 건 종료하기.bat 입니다.

실행
  python launcher.py               봇 2개 + 상태판을 켜고 상태판 창을 엽니다
  python launcher.py --no-open     창은 열지 않습니다
  python launcher.py --stop        켜 둔 봇과 상태판을 끕니다
  python launcher.py --update      새 버전을 확인하고 지금 업데이트합니다
  python launcher.py --no-update   이번 실행에서는 업데이트를 확인하지 않습니다
  python launcher.py --version     버전만 출력합니다

Python 3.9 이상. 봇 패키지는 실행하기.bat 이 .venv 에 설치합니다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
PID_FILE = LOG_DIR / "launcher.json"
VERSION_FILE = BASE_DIR / "version.json"
LAUNCHER_LOG = LOG_DIR / "launcher.log"
UPDATE_RECORD = LOG_DIR / "update.json"

HUB_HOST = "127.0.0.1"
HUB_PORT = 8771

# ── 앱 정보 · 업데이트 ──
APP_NAME = "백수톡 디코봇"
REPO = "anchirong9-arch/discord-bots-launcher"
RAW_VERSION_URL = "https://raw.githubusercontent.com/%s/main/version.json" % REPO
PAGES_VERSION_URL = "https://anchirong9-arch.github.io/discord-bots-launcher/version.json"
DEFAULT_ZIP_URL = "https://github.com/%s/releases/latest/download/discord-bots-launcher.zip" % REPO
UPDATE_TIMEOUT = 3.0        # 버전 확인 — 느리면 그냥 넘어갑니다
DOWNLOAD_TIMEOUT = 30.0     # ZIP 내려받기
USER_AGENT = "DiscordBotsLauncher"

# 업데이트할 때 절대 건드리지 않는 것들 (.env 토큰·설정·로그 보존)
PRESERVE_DIRS = {".venv", ".git", "logs", "updates", "__pycache__", "bin", "attachments"}
PRESERVE_SUFFIXES = {".env", ".pyc", ".log"}
PRESERVE_NAMES = {"cookies.txt", "launcher.json", "update.json"}


def _load_version() -> str:
    try:
        data = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("version"):
            return str(data["version"])
    except Exception:  # noqa: BLE001
        pass
    return "1.0.0"


SERVER_VERSION = _load_version()

# ── 디스코드 봇 2종 ──
BOTS = [
    {
        "id": "log-bot",
        "name": "료그봇",
        "folder": "tools/log-bot",
        "modules": ["discord", "dotenv"],
        "hint": "discord.py · python-dotenv",
        # 기존 봇 폴더의 .env 와 같은 기본값 — 토큰만 넣어도 바로 기록이 시작됩니다.
        "env_defaults": [
            ("SOURCE_GUILD_ID", "386882960403726337"),
            ("LOG_CHANNEL_ID", "1572394445142360064"),
            ("LOG_USER_ID", ""),
        ],
        "token_url": "https://discord.com/developers/applications/1572393464576876594/bot",
        "invite": "https://discord.com/oauth2/authorize?client_id=1572393464576876594&permissions=117888&integration_type=0&scope=bot",
        "desc": "백수톡의 사진·파일·삭제·수정·입퇴장·음성까지 내 개인 서버 #백수톡-로그에 원본 그대로 남겨요.",
        "meta": "백수톡 로그 · 사진 원본 보존",
    },
    {
        "id": "music-bot",
        "name": "뮤직봇",
        "folder": "tools/music-bot",
        "modules": ["discord", "dotenv", "yt_dlp"],
        "hint": "discord.py · yt-dlp · PyNaCl",
        "env_defaults": [],
        "token_url": "https://discord.com/developers/applications/1572389279139758090/bot",
        "invite": "https://discord.com/oauth2/authorize?client_id=1572389279139758090&permissions=3165184&integration_type=0&scope=bot+applications.commands",
        "desc": "음성 채널에서 유튜브 곡을 틀어 줘요. /r 재생 · /s 스킵 · /q 대기열 · /x 나가기.",
        "meta": "유튜브 음악 · /r /s /q /x",
        "needs_ffmpeg": True,
    },
]
BOT_BY_ID = {b["id"]: b for b in BOTS}

# 봇 토큰 자리에 그대로 남아 있는 예시 문자열 — 이건 '토큰 없음'으로 봅니다.
PLACEHOLDER_TOKENS = {
    "여기에_봇_토큰을_붙여넣으세요", "여기에_봇_토큰", "여기에_봇토큰", "여기에봇토큰",
    "your_token", "your-token", "yourtoken", "token", "xxx", "none", "null",
}
BOT_READY_MARKS = ("로그인 완료", "준비 완료!")
BOT_FAIL_MARKS = (
    "LoginFailure", "Improper token", "토큰이 올바르지 않습니다",
    "DISCORD_TOKEN 이 없습니다", "ModuleNotFoundError", "No module named",
)

_STATE_LOCK = threading.Lock()
_STATE = {
    "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    "bots": {},           # id -> {"started_at": str, "note": str, "error": str}
    "shutting_down": False,
}
_BOT_PROC: dict[str, subprocess.Popen] = {}
_BOT_RUN: dict[str, dict] = {}   # id -> {"offset": int, "ready": bool, "error": str, "started": float}
_HUB_SERVER: ThreadingHTTPServer | None = None
_STOP_EVENT = threading.Event()


# ───────────────────────────── 공용 도우미 ─────────────────────────────

def _append_log(line: str) -> None:
    """pythonw(콘솔 없음)에서도 남도록 파일에도 씁니다. 400KB 넘으면 한 번 비웁니다."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if LAUNCHER_LOG.exists() and LAUNCHER_LOG.stat().st_size > 400_000:
            try:
                LAUNCHER_LOG.replace(LAUNCHER_LOG.with_suffix(".log.1"))
            except OSError:
                LAUNCHER_LOG.unlink(missing_ok=True)
        with LAUNCHER_LOG.open("a", encoding="utf-8") as fp:
            fp.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
    except Exception:  # noqa: BLE001
        pass


def log(msg: str) -> None:
    line = "[런처] " + str(msg)
    _append_log(line)
    if sys.stdout is not None:
        try:
            print(line, flush=True)
        except Exception:  # noqa: BLE001
            pass


def warn(msg: str) -> None:
    line = "[런처] ! " + str(msg)
    _append_log(line)
    if sys.stdout is not None:
        try:
            print(line, flush=True)
        except Exception:  # noqa: BLE001
            pass


def http_json(url: str, timeout: float = 1.5) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:
            if getattr(res, "status", 200) != 200:
                return None
            obj = json.loads(res.read().decode("utf-8", "replace"))
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        return None


def which_python() -> str:
    return sys.executable or "python"


def kill_pid(pid: int | None) -> None:
    if not pid:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=15)
        except Exception:  # noqa: BLE001
            pass
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid],
                                 capture_output=True, timeout=10).stdout
            return str(pid).encode() in out
        except Exception:  # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pid_file() -> dict:
    try:
        return json.loads(PID_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def write_pid_file() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with _STATE_LOCK:
        snapshot = {
            "hub": {"pid": os.getpid(), "port": HUB_PORT},
            "started_at": _STATE["started_at"],
            "bots": {
                bid: {"pid": proc.pid, "owned": True}
                for bid, proc in _BOT_PROC.items()
                if proc.poll() is None
            },
        }
    try:
        PID_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def set_bot_state(bot_id: str, **kw) -> None:
    with _STATE_LOCK:
        info = _STATE["bots"].setdefault(bot_id, {"started_at": "", "note": "", "error": ""})
        info.update(kw)


# ───────────────────────────── .env · 토큰 ─────────────────────────────

def bot_dir(bot: dict) -> Path:
    return BASE_DIR.joinpath(*bot["folder"].split("/"))


def bot_script(bot: dict) -> Path:
    return bot_dir(bot) / "bot.py"


def bot_env_path(bot: dict) -> Path:
    return bot_dir(bot) / ".env"


def bot_log_path(bot: dict) -> Path:
    return LOG_DIR / (bot["id"] + ".log")


def parse_env_text(text: str) -> dict:
    """.env 파일 내용을 key=value 로 읽습니다. (dotenv 없이 처리)"""
    data: dict[str, str] = {}
    for line in str(text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, value = s.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            data[key] = value
    return data


def clean_token(value: str) -> str:
    """.env 에 남아 있는 예시 문구·따옴표·공백을 걸러 냅니다."""
    token = str(value or "").strip().strip("\"'").strip()
    if not token:
        return ""
    if token in PLACEHOLDER_TOKENS or token.lower() in PLACEHOLDER_TOKENS:
        return ""
    if "붙여넣" in token or token.startswith("<") or token.startswith("여기에"):
        return ""
    if any(ch.isspace() for ch in token):
        return ""
    return token


def token_looks_valid(token: str) -> bool:
    """디스코드 봇 토큰은 'xxxxx.yyyyy.zzzzz' 형태입니다."""
    return len(token) >= 40 and token.count(".") >= 2


def token_hint(token: str) -> str:
    if not token:
        return ""
    return "%s… (%d자)" % (token[:4], len(token))


def bot_env_data(bot: dict) -> dict:
    try:
        return parse_env_text(bot_env_path(bot).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


def bot_token(bot: dict) -> str:
    return clean_token(bot_env_data(bot).get("DISCORD_TOKEN", ""))


def bot_modules_ok(bot: dict) -> bool:
    if not bot["modules"]:
        return True
    code = "import " + ", ".join(bot["modules"])
    try:
        return subprocess.run([which_python(), "-c", code],
                              capture_output=True, timeout=40).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def ffmpeg_for_bot() -> str:
    """뮤직봇이 쓸 ffmpeg — FFMPEG_PATH → tools/music-bot/bin → imageio-ffmpeg → PATH."""
    env_path = (os.getenv("FFMPEG_PATH") or "").strip().strip('"')
    if env_path and Path(env_path).is_file():
        return env_path
    for name in ("ffmpeg.exe", "ffmpeg"):
        candidate = bot_dir(BOT_BY_ID["music-bot"]) / "bin" / name
        if candidate.is_file():
            return str(candidate)
    try:
        import imageio_ffmpeg  # type: ignore
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return exe
    except Exception:  # noqa: BLE001
        pass
    return shutil.which("ffmpeg") or ""


def _redact(text: str) -> str:
    """로그에 혹시 찍혔을 토큰 모양 문자열은 가립니다."""
    return re.sub(r"[A-Za-z0-9_-]{18,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{18,}", "•••", str(text or ""))


def bot_log_size(bot: dict) -> int:
    try:
        return bot_log_path(bot).stat().st_size
    except OSError:
        return 0


def bot_log_since(bot: dict, offset: int) -> str:
    try:
        with bot_log_path(bot).open("rb") as fp:
            fp.seek(max(0, offset))
            return fp.read().decode("utf-8", "replace")
    except OSError:
        return ""


def bot_run_state(bot: dict) -> dict:
    """이번 실행에서 '연결됨' 표시가 로그에 나왔는지 확인합니다."""
    run = _BOT_RUN.get(bot["id"])
    if not run:
        return {"ready": False, "error": "", "text": ""}
    text = bot_log_since(bot, int(run.get("offset") or 0))
    if not run.get("ready") and any(mark in text for mark in BOT_READY_MARKS):
        run["ready"] = True
        run["ready_at"] = time.strftime("%H:%M:%S")
    if not run.get("error"):
        for mark in BOT_FAIL_MARKS:
            if mark in text:
                run["error"] = mark
                break
    return {"ready": bool(run.get("ready")), "error": str(run.get("error") or ""), "text": text}


# ───────────────────────────── 봇 켜기 / 끄기 ─────────────────────────────

def spawn_bot(bot: dict) -> dict:
    """봇 하나를 백그라운드로 켭니다. 토큰이 없으면 에러가 아니라 '토큰 필요'로 돌려줍니다."""
    bid = bot["id"]

    if not bot_token(bot):
        set_bot_state(bid, error="", note="토큰 설정 필요")
        return {"ok": False, "needToken": True,
                "error": "봇 토큰이 없어요. .env 를 넣거나 상태판의 '토큰 넣기'를 눌러 주세요."}

    script = bot_script(bot)
    if not script.is_file():
        msg = "%s/bot.py 가 없습니다. ZIP 압축을 제대로 풀었는지 확인해 주세요." % bot["folder"]
        set_bot_state(bid, error=msg, note="")
        warn("%s — %s" % (bot["name"], msg))
        return {"ok": False, "error": msg}

    proc = _BOT_PROC.get(bid)
    if proc is not None and proc.poll() is None:
        return {"ok": True, "already": True, "pid": proc.pid}

    if not bot_modules_ok(bot):
        warn("%s — %s 패키지가 아직 없어요. 실행하기.bat 을 다시 실행하면 설치됩니다."
             % (bot["name"], bot["hint"]))

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = bot_log_path(bot)
    offset = bot_log_size(bot)
    header = "\n===== 런처가 봇을 켰습니다 (%s · v%s) =====\n" % (
        time.strftime("%Y-%m-%d %H:%M:%S"), SERVER_VERSION)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("PORT", None)          # Render 용 상태 서버는 로컬에서 끕니다
    if bot.get("needs_ffmpeg"):
        ffmpeg_path = ffmpeg_for_bot()
        if ffmpeg_path:
            env["FFMPEG_PATH"] = ffmpeg_path

    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

    log_handle = None
    try:
        log_handle = open(log_path, "ab", buffering=0)
        log_handle.write(header.encode("utf-8"))
        proc = subprocess.Popen(
            [which_python(), "-u", str(script)],
            cwd=str(bot_dir(bot)),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=env,
            **kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        msg = "봇을 시작하지 못했습니다: %s" % exc
        set_bot_state(bid, error=msg, note="")
        warn("%s — %s" % (bot["name"], msg))
        return {"ok": False, "error": msg}
    finally:
        if log_handle is not None:
            try:
                log_handle.close()
            except OSError:
                pass

    _BOT_PROC[bid] = proc
    _BOT_RUN[bid] = {"offset": offset, "ready": False, "error": "", "started": time.time()}
    set_bot_state(bid, error="", note="", started_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    log("%s 를 켰습니다. (pid %d)" % (bot["name"], proc.pid))
    return {"ok": True, "pid": proc.pid}


def stop_bot(bot: dict) -> dict:
    bid = bot["id"]
    stopped = False
    proc = _BOT_PROC.get(bid)
    if proc is not None and proc.poll() is None:
        kill_pid(proc.pid)
        stopped = True
    if not stopped:
        info = (read_pid_file().get("bots") or {}).get(bid, {})
        if info.get("pid") and info.get("owned") and pid_alive(info.get("pid")):
            kill_pid(info["pid"])
            stopped = True
    _BOT_PROC.pop(bid, None)
    _BOT_RUN.pop(bid, None)
    set_bot_state(bid, error="", note="", started_at="")
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with bot_log_path(bot).open("a", encoding="utf-8") as fp:
            fp.write("%s ===== 런처가 봇을 껐습니다 =====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
    except OSError:
        pass
    if stopped:
        log("%s 를 껐습니다." % bot["name"])
    return {"ok": True, "stopped": stopped}


def save_bot_env(bot: dict, raw_text: str) -> dict:
    """.env 내용(또는 토큰만)을 받아 이 PC의 봇 폴더에 저장합니다. GitHub 에는 올라가지 않습니다."""
    text = str(raw_text or "").strip()
    if not text:
        return {"ok": False, "error": "붙여넣은 내용이 비어 있어요."}

    parsed = parse_env_text(text)
    token = clean_token(parsed.get("DISCORD_TOKEN", ""))
    if not token:                                  # .env 형식이 아니라 토큰만 붙여넣은 경우
        first = text.splitlines()[0].strip() if text.splitlines() else ""
        token = clean_token(first)
    if not token:
        return {"ok": False,
                "error": "DISCORD_TOKEN 값을 찾지 못했어요. .env 내용을 통째로 붙여넣거나 토큰만 붙여넣어 주세요."}
    if not token_looks_valid(token):
        return {"ok": False,
                "error": "토큰 형식이 아니에요. 개발자 포털 Bot → Reset Token 에서 복사한 값을 넣어 주세요."}

    env_path = bot_env_path(bot)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing = bot_env_data(bot)

    merged: dict[str, str] = {}
    for key, value in parsed.items():              # 사용자가 넣은 다른 설정은 그대로 살립니다
        if key != "DISCORD_TOKEN":
            merged[key] = value
    for key, default in bot["env_defaults"]:
        if key not in merged and key not in existing:
            merged[key] = default
    for key, value in existing.items():            # 기존 .env 의 나머지 값도 유지
        if key not in merged and key != "DISCORD_TOKEN":
            merged[key] = value

    lines = ["# 백수톡 디코봇 런처가 저장했습니다. 이 파일은 이 PC에만 있고 GitHub·디스코드에 올라가지 않아요.",
             "DISCORD_TOKEN=%s" % token]
    for key, value in merged.items():
        lines.append("%s=%s" % (key, value))
    try:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            os.chmod(env_path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        return {"ok": False, "error": "저장하지 못했어요: %s" % exc}

    result = {"ok": True, "tokenHint": token_hint(token),
              "path": str(env_path.relative_to(BASE_DIR)), "restarted": False, "started": False}

    proc = _BOT_PROC.get(bot["id"])
    if proc is not None and proc.poll() is None:
        stop_bot(bot)
        result["restarted"] = bool(spawn_bot(bot).get("ok"))
    elif proc is None:
        result["started"] = bool(spawn_bot(bot).get("ok"))

    log("%s 토큰을 저장했습니다 (%s)." % (bot["name"], result["path"]))
    return result


def bot_status(bot: dict) -> dict:
    bid = bot["id"]
    token = bot_token(bot)
    with _STATE_LOCK:
        info = dict(_STATE["bots"].get(bid, {}))
    proc = _BOT_PROC.get(bid)
    alive = bool(proc is not None and proc.poll() is None)
    run = bot_run_state(bot)
    env_path = bot_env_path(bot)

    error = ""
    if not token:
        state, label = "token", "토큰 미설정"
        detail = "토큰을 한 번만 넣으면 다음부터 자동으로 켜져요"
    elif alive and run["ready"]:
        state, label = "online", "온라인"
        detail = "디스코드에 연결됨 · %s 시작" % (info.get("started_at", "") or "이번 실행")
    elif alive:
        state, label = "starting", "켜는 중"
        detail = "디스코드에 연결하는 중…"
    elif run["error"]:
        state, label = "error", "오류"
        error = run["error"]
        detail = "봇이 로그인하지 못했어요 — 토큰을 다시 넣어 주세요"
    else:
        state, label = "offline", "오프라인"
        detail = "'켜기'를 누르면 바로 켜져요"

    tail = ""
    if state == "error" or not alive:
        tail = _redact(bot_log_since(bot, max(0, bot_log_size(bot) - 900)).strip())

    return {
        "id": bid,
        "name": bot["name"],
        "folder": bot["folder"],
        "desc": bot["desc"],
        "meta": bot["meta"],
        "tokenSet": bool(token),
        "tokenHint": token_hint(token),
        "envPath": str(env_path.relative_to(BASE_DIR)),
        "envExists": env_path.is_file(),
        "state": state,
        "label": label,
        "online": state == "online",
        "running": alive,
        "pid": proc.pid if alive else None,
        "detail": detail,
        "error": error,
        "note": info.get("note", ""),
        "startedAt": info.get("started_at", ""),
        "tail": tail,
        "modulesOk": bot_modules_ok(bot),
        "hint": bot["hint"],
        "tokenUrl": bot["token_url"],
        "invite": bot["invite"],
    }


def start_bots() -> None:
    """실행 시 자동으로 — 토큰이 있는 봇만 켭니다. 없으면 상태만 '토큰 미설정'."""
    for bot in BOTS:
        if not bot_token(bot):
            set_bot_state(bot["id"], note="토큰 설정 필요", error="")
            log("%s — 토큰이 아직 없어서 켜지 않았습니다. (.env 를 넣거나 상태판에서 설정)" % bot["name"])
            continue
        result = spawn_bot(bot)
        if not result.get("ok"):
            log("%s 를 켜지 못했습니다: %s" % (bot["name"], result.get("error")))


def wait_bots_ready(total_wait: float = 15.0) -> None:
    """켜는 중인 봇이 로그인을 마칠 때까지 조금 기다리며 알려 줍니다."""
    deadline = time.time() + max(0.0, total_wait)
    while time.time() < deadline:
        pending = []
        for bot in BOTS:
            proc = _BOT_PROC.get(bot["id"])
            if proc is None or proc.poll() is not None:
                continue
            if not bot_run_state(bot)["ready"]:
                pending.append(bot)
        if not pending:
            break
        time.sleep(0.5)
    for bot in BOTS:
        if bot["id"] not in _BOT_PROC:
            continue
        st = bot_status(bot)
        if st["state"] == "online":
            log("%s 온라인 — 디스코드에 연결됐습니다." % bot["name"])
        elif st["state"] == "starting":
            log("%s 는 아직 연결 중입니다. 상태판에서 다시 확인해 주세요." % bot["name"])
        elif st["state"] == "error":
            warn("%s 로그인 실패 — 토큰을 확인해 주세요. (logs/%s.log)" % (bot["name"], bot["id"]))
    write_pid_file()


# ───────────────────────────── 자동 업데이트 ─────────────────────────────

_UPDATE_LOCK = threading.Lock()
_UPDATE = {"latest": None, "checked_at": None, "error": "", "applied": None}


def _parse_version(text) -> tuple:
    """'v1.0.10' → (1, 0, 10) 처럼 숫자만 비교합니다."""
    nums = [int(n) for n in re.findall(r"\d+", str(text or ""))][:4]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def _version_urls() -> list[str]:
    urls: list[str] = []
    try:
        local = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        local = {}
    for candidate in (local.get("version_url"), RAW_VERSION_URL, PAGES_VERSION_URL):
        if candidate and str(candidate) not in urls:
            urls.append(str(candidate))
    return urls


def fetch_remote_version(timeout: float = UPDATE_TIMEOUT) -> dict | None:
    """GitHub 의 version.json 을 짧게 확인합니다. 실패(오프라인·타임아웃)하면 None."""
    deadline = time.time() + max(1.0, timeout)
    for url in _version_urls():
        remaining = deadline - time.time()
        if remaining <= 0.3:
            break
        sep = "&" if "?" in url else "?"
        req_url = "%s%st=%d" % (url, sep, int(time.time() * 1000))
        try:
            req = urllib.request.Request(req_url, headers={
                "Cache-Control": "no-cache",
                "User-Agent": "%s/%s" % (USER_AGENT, SERVER_VERSION),
            })
            with urllib.request.urlopen(req, timeout=remaining) as res:
                data = json.loads(res.read().decode("utf-8", "replace"))
            if isinstance(data, dict) and data.get("version"):
                return data
        except Exception:  # noqa: BLE001
            continue
    return None


def update_status() -> dict:
    with _UPDATE_LOCK:
        latest = _UPDATE["latest"] or {}
        checked_at = _UPDATE["checked_at"]
        error = _UPDATE["error"] or ""
        applied = _UPDATE["applied"]
    latest_version = str(latest.get("version") or "")
    return {
        "version": SERVER_VERSION,
        "latest": latest_version,
        "updateAvailable": bool(latest_version) and _parse_version(latest_version) > _parse_version(SERVER_VERSION),
        "checked": checked_at is not None,
        "checkedAt": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(checked_at)) if checked_at else "",
        "notes": latest.get("notes") or [],
        "zip": latest.get("zip") or DEFAULT_ZIP_URL,
        "error": error,
        "applied": applied,
    }


def _skip_in_update(rel: Path) -> bool:
    """업데이트로 덮어쓰면 안 되는 파일인가? (.env·로그·bin 등)"""
    if any(part in PRESERVE_DIRS for part in rel.parts[:-1]):
        return True
    if rel.name in PRESERVE_NAMES or rel.suffix.lower() in PRESERVE_SUFFIXES:
        return True
    if rel.name.endswith(".env"):
        return True
    return False


def _extract_zip(zip_path: Path, dest: Path) -> None:
    """경로 탈출(../) 을 막으면서 풉니다."""
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts or re.match(r"^[A-Za-z]:", name):
                raise ValueError("압축 파일에 이상한 경로가 있어요: %s" % name)
            target = dest.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)


def _zip_candidates(remote: dict) -> list[str]:
    urls: list[str] = []
    for candidate in (remote.get("zip"), remote.get("zip_fallback"), DEFAULT_ZIP_URL):
        if candidate and str(candidate) not in urls:
            urls.append(str(candidate))
    return urls


def _stage_zip(url: str, tmpdir: Path, target_version: str) -> Path:
    """ZIP 하나를 받아 풀고 검증합니다. 이상하면 예외."""
    zip_path = tmpdir / "update.zip"
    log("v%s 내려받는 중... (%s)" % (target_version, url.split("//")[-1][:60]))
    req = urllib.request.Request(url, headers={
        "User-Agent": "%s/%s" % (USER_AGENT, SERVER_VERSION),
        "Accept": "application/zip, application/octet-stream",
    })
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as res, zip_path.open("wb") as out:
        shutil.copyfileobj(res, out, 1 << 20)

    stage = tmpdir / ("x%d" % int(time.time() * 1000))
    _extract_zip(zip_path, stage)

    root = stage
    if not (root / "launcher.py").is_file():          # ZIP 안에 폴더 하나만 있는 경우
        dirs = [p for p in stage.iterdir() if p.is_dir()]
        if len(dirs) == 1:
            root = dirs[0]
    if not (root / "launcher.py").is_file() or not (root / "version.json").is_file():
        raise ValueError("받은 ZIP 이 런처 파일이 아니에요.")

    packed = json.loads((root / "version.json").read_text(encoding="utf-8"))
    if _parse_version(packed.get("version")) < _parse_version(target_version):
        raise ValueError("ZIP 안의 버전(%s)이 안내된 버전(%s)보다 낮아요." % (packed.get("version"), target_version))
    return root


def apply_update(remote: dict | None = None, reason: str = "startup") -> dict:
    """최신 ZIP 을 받아 이 폴더를 덮어씁니다. .env·로그·bin·cookies.txt 는 보존."""
    remote = remote or fetch_remote_version()
    if not remote:
        with _UPDATE_LOCK:
            _UPDATE["error"] = "최신 버전 정보를 받지 못했어요."
            _UPDATE["checked_at"] = time.time()
        return {"ok": False, "error": "최신 버전 정보를 받지 못했어요. (오프라인일 수 있어요)"}

    target_version = str(remote.get("version") or "")
    with _UPDATE_LOCK:
        _UPDATE["latest"] = remote
        _UPDATE["checked_at"] = time.time()
        _UPDATE["error"] = ""

    if _parse_version(target_version) <= _parse_version(SERVER_VERSION):
        return {"ok": True, "uptodate": True, "version": SERVER_VERSION}

    tmpdir = Path(tempfile.mkdtemp(prefix="discord-bots-update-"))
    try:
        root = None
        errors: list[str] = []
        for url in _zip_candidates(remote):
            try:
                root = _stage_zip(url, tmpdir, target_version)
                break
            except Exception as exc:  # noqa: BLE001
                errors.append("%s: %s" % (url.rsplit("/", 1)[-1], exc))
                log("이 주소로는 받지 못했습니다 — %s" % exc)
        if root is None:
            raise ValueError("업데이트 파일을 받지 못했어요. " + " / ".join(errors[:2]))

        backup = LOG_DIR / "backup"
        backup.mkdir(parents=True, exist_ok=True)
        copied = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if _skip_in_update(rel):
                continue
            dest = BASE_DIR.joinpath(*rel.parts)
            if len(rel.parts) == 1 and dest.is_file():      # 최상위 파일은 백업해 둠
                try:
                    shutil.copy2(dest, backup / rel.name)
                except OSError:
                    pass
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            copied += 1

        with _UPDATE_LOCK:
            _UPDATE["applied"] = target_version
        try:
            UPDATE_RECORD.write_text(json.dumps({
                "version": target_version,
                "previous": SERVER_VERSION,
                "applied_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "reason": reason,
                "files": copied,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        log("업데이트 완료: v%s → v%s (%d개 파일)" % (SERVER_VERSION, target_version, copied))
        return {"ok": True, "version": target_version, "previous": SERVER_VERSION, "files": copied}
    except Exception as exc:  # noqa: BLE001
        with _UPDATE_LOCK:
            _UPDATE["error"] = str(exc)
        log("업데이트를 건너뛰었습니다: %s" % exc)
        return {"ok": False, "error": str(exc)}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def auto_update_at_start() -> None:
    """실행 직전에 한 번만. 실패하면 조용히 현재 버전으로 진행합니다."""
    if os.environ.get("DISCORD_BOTS_UPDATED") == "1":
        return
    remote = fetch_remote_version()
    with _UPDATE_LOCK:
        _UPDATE["checked_at"] = time.time()
        if remote:
            _UPDATE["latest"] = remote
            _UPDATE["error"] = ""
        else:
            _UPDATE["error"] = "버전 확인 실패 (오프라인?)"
    if not remote:
        log("새 버전 확인을 건너뜁니다. v%s 로 실행합니다." % SERVER_VERSION)
        return
    if _parse_version(remote["version"]) <= _parse_version(SERVER_VERSION):
        log("최신 버전입니다. (v%s)" % SERVER_VERSION)
        return

    result = apply_update(remote, "startup")
    if not result.get("ok"):
        log("지금은 v%s 로 계속 실행합니다." % SERVER_VERSION)
        return

    os.environ["DISCORD_BOTS_UPDATED"] = "1"
    log("새 버전 v%s 로 다시 시작합니다..." % result.get("version"))
    try:
        os.execv(sys.executable, [sys.executable, str(BASE_DIR / "launcher.py")] + sys.argv[1:])
    except Exception as exc:  # noqa: BLE001
        log("다시 시작하지 못했습니다(%s). 이번에는 v%s 로 실행하고, 다음 실행부터 새 버전입니다."
            % (exc, SERVER_VERSION))


# ───────────────────────────── 상태판 창 열기 ─────────────────────────────

def _browser_exe() -> list[Path]:
    """Edge → Chrome 순서로 설치된 실행 파일을 찾습니다."""
    if os.name != "nt":
        return []
    found: list[Path] = []
    envs = [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")]
    rels = [
        r"Microsoft\Edge\Application\msedge.exe",
        r"Google\Chrome\Application\chrome.exe",
        r"Microsoft\Edge Beta\Application\msedge.exe",
    ]
    for base in envs:
        if not base:
            continue
        for rel in rels:
            cand = Path(base) / rel
            if cand.is_file() and cand not in found:
                found.append(cand)
    return found


def open_app_window(url: str) -> bool:
    """주소창 없는 앱 창(Edge/Chrome --app)으로 엽니다. 없으면 기본 브라우저."""
    for exe in _browser_exe():
        try:
            kwargs = {}
            if os.name == "nt":
                kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
            subprocess.Popen(
                [str(exe), "--app=" + url, "--window-size=760,720",
                 "--no-first-run", "--no-default-browser-check"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, **kwargs,
            )
            log("상태판을 앱 창으로 열었습니다 (%s)" % exe.name)
            return True
        except Exception:  # noqa: BLE001
            continue
    try:
        webbrowser.open(url)
        log("기본 브라우저로 열었습니다: %s" % url)
        return True
    except Exception:  # noqa: BLE001
        return False


# ───────────────────────────── 상태판 서버 ─────────────────────────────

def snapshot() -> dict:
    return {
        "ok": True,
        "app": "discord-bots-launcher",
        "version": SERVER_VERSION,
        "hub": {"port": HUB_PORT, "pid": os.getpid(), "started_at": _STATE["started_at"]},
        "bots": [bot_status(b) for b in BOTS],
    }


class HubHandler(SimpleHTTPRequestHandler):
    server_version = "DiscordBotsLauncher/%s" % SERVER_VERSION

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def log_message(self, fmt, *args):  # 콘솔을 조용하게
        pass

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "86400")

    def json_out(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.cors()
        super().end_headers()

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/api/status", "/health"):
            return self.json_out(snapshot())
        if path == "/api/version":
            return self.json_out(dict({"ok": True, "app": "discord-bots-launcher"}, **update_status()))
        if path.startswith("/api/log"):
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
            bid = params.get("bot", "")
            bot = BOT_BY_ID.get(bid)
            if not bot:
                return self.json_out({"ok": False, "error": "알 수 없는 봇입니다."}, 400)
            tail = _redact(bot_log_since(bot, max(0, bot_log_size(bot) - 8000)))
            return self.json_out({"ok": True, "bot": bid, "log": tail})
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8", "replace") or "{}")
        except Exception:  # noqa: BLE001
            payload = {}

        if path == "/api/start":
            bot = BOT_BY_ID.get(str(payload.get("bot") or ""))
            if not bot:
                return self.json_out({"ok": False, "error": "알 수 없는 봇입니다."}, 400)
            result = spawn_bot(bot)
            return self.json_out({"ok": bool(result.get("ok")), "result": result,
                                  "status": bot_status(bot)}, 200 if result.get("ok") else 409)

        if path == "/api/stop":
            bot = BOT_BY_ID.get(str(payload.get("bot") or ""))
            if not bot:
                return self.json_out({"ok": False, "error": "알 수 없는 봇입니다."}, 400)
            result = stop_bot(bot)
            return self.json_out({"ok": True, **result, "status": bot_status(bot)})

        if path == "/api/restart":
            bot = BOT_BY_ID.get(str(payload.get("bot") or ""))
            if not bot:
                return self.json_out({"ok": False, "error": "알 수 없는 봇입니다."}, 400)
            stop_bot(bot)
            result = spawn_bot(bot)
            return self.json_out({"ok": bool(result.get("ok")), "result": result,
                                  "status": bot_status(bot)}, 200 if result.get("ok") else 409)

        if path == "/api/env":
            bot = BOT_BY_ID.get(str(payload.get("bot") or ""))
            if not bot:
                return self.json_out({"ok": False, "error": "알 수 없는 봇입니다."}, 400)
            result = save_bot_env(bot, str(payload.get("text") or ""))
            return self.json_out({**result, "status": bot_status(bot)},
                                 200 if result.get("ok") else 400)

        if path == "/api/update/check":
            remote = fetch_remote_version()
            with _UPDATE_LOCK:
                _UPDATE["checked_at"] = time.time()
                if remote:
                    _UPDATE["latest"] = remote
                    _UPDATE["error"] = ""
                else:
                    _UPDATE["error"] = "버전 정보를 받지 못했어요 (오프라인?)"
            return self.json_out({"ok": True, **update_status()})

        if path == "/api/update/apply":
            result = apply_update(reason="hub")
            return self.json_out({**result, "status": update_status()}, 200 if result.get("ok") else 502)

        if path == "/api/shutdown":
            stopped = []
            for bot in BOTS:
                if bot["id"] in _BOT_PROC and _BOT_PROC[bot["id"]].poll() is None:
                    stop_bot(bot)
                    stopped.append(bot["name"])
            self.json_out({"ok": True, "stopped": stopped,
                           "message": ("%s를 껐습니다." % ", ".join(stopped)) if stopped else "켜 둔 봇이 없습니다."})
            threading.Thread(target=finish_shutdown, name="shutdown", daemon=True).start()
            return

        return self.json_out({"ok": False, "error": "알 수 없는 요청입니다."}, 404)


def start_hub() -> bool:
    global _HUB_SERVER
    existing = http_json("http://%s:%d/api/status" % (HUB_HOST, HUB_PORT), 0.8)
    if existing and existing.get("app") == "discord-bots-launcher":
        log("이미 실행 중인 런처를 찾았습니다. (http://%s:%d/)" % (HUB_HOST, HUB_PORT))
        return False
    try:
        _HUB_SERVER = ThreadingHTTPServer((HUB_HOST, HUB_PORT), HubHandler)
    except OSError as exc:
        warn("상태판 포트 %d 를 열지 못했습니다: %s" % (HUB_PORT, exc))
        return False
    _HUB_SERVER.daemon_threads = True
    threading.Thread(target=_HUB_SERVER.serve_forever, name="hub", daemon=True).start()
    return True


# ───────────────────────────── 종료 ─────────────────────────────

def stop_all_bots() -> list[str]:
    stopped: list[str] = []
    for bid, proc in list(_BOT_PROC.items()):
        if proc.poll() is None:
            kill_pid(proc.pid)
            stopped.append(bid)
        _BOT_PROC.pop(bid, None)
    _BOT_RUN.clear()
    for bid, info in (read_pid_file().get("bots") or {}).items():
        if info.get("owned") and info.get("pid") and bid not in stopped:
            kill_pid(info["pid"])
            stopped.append(bid)
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    return stopped


def finish_shutdown() -> None:
    _STOP_EVENT.set()
    if _HUB_SERVER is not None:
        threading.Timer(0.2, _HUB_SERVER.shutdown).start()


def shutdown_all(reason: str = "") -> None:
    with _STATE_LOCK:
        if _STATE["shutting_down"]:
            return
        _STATE["shutting_down"] = True
    if reason:
        log(reason)
    stopped = stop_all_bots()
    if stopped:
        log("봇을 정리했습니다: " + ", ".join(BOT_BY_ID[b]["name"] for b in stopped if b in BOT_BY_ID))
    finish_shutdown()


def install_console_handlers() -> None:
    def _graceful(signum, frame):  # noqa: ARG001
        shutdown_all("종료 신호를 받았습니다. 봇을 정리하는 중...")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _graceful)
        except Exception:  # noqa: BLE001
            pass
    if os.name == "nt":
        try:
            import ctypes
            prototype = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)

            def _console_event(ctrl_type):
                shutdown_all("창이 닫혀 봇을 정리하는 중...")
                time.sleep(0.4)
                return True

            handler = prototype(_console_event)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)
            globals()["_console_handler_ref"] = handler
        except Exception:  # noqa: BLE001
            pass


def stop_everything() -> int:
    data = read_pid_file()
    stopped = []
    for bid, info in (data.get("bots") or {}).items():
        pid = info.get("pid")
        if pid and info.get("owned") and pid_alive(pid):
            kill_pid(pid)
            stopped.append("%s (pid %s)" % (BID_NAME.get(bid, bid), pid))
    hub = (data.get("hub") or {})
    if hub.get("pid") and pid_alive(hub["pid"]) and hub["pid"] != os.getpid():
        kill_pid(hub["pid"])
        stopped.append("상태판 (pid %s)" % hub["pid"])
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    if stopped:
        log("정리했습니다: " + ", ".join(stopped))
    else:
        log("켜 둔 봇이 없습니다.")
    return 0


BID_NAME = {b["id"]: b["name"] for b in BOTS}


# ───────────────────────────── main ─────────────────────────────

def print_banner() -> None:
    log("=" * 58)
    log("   %s v%s — 료그봇 · 뮤직봇 한 번에" % (APP_NAME, SERVER_VERSION))
    log("=" * 58)


def print_status_table() -> None:
    log("")
    for bot in BOTS:
        st = bot_status(bot)
        log("  [%s] %-8s %s" % (st["label"], st["name"], st["detail"]))
        if st["error"]:
            log("        ! " + st["error"].replace("\n", " ")[:160])
    log("  상태판: http://127.0.0.1:%d/   (창을 닫아도 봇은 계속 돕니다 · 끄기: 종료하기.bat)" % HUB_PORT)
    log("  로그: logs/launcher.log · 봇별 로그: logs/log-bot.log · logs/music-bot.log")


def monitor() -> None:
    """봇이 도중에 죽으면 로그에 알려 줍니다."""
    last: dict[str, str] = {}
    while not _STOP_EVENT.is_set():
        for bot in BOTS:
            st = bot_status(bot)
            prev = last.get(bot["id"])
            if prev is not None and prev != st["state"]:
                if st["state"] == "online":
                    log("%s 온라인 — 디스코드에 연결됐습니다." % bot["name"])
                elif st["state"] == "error":
                    warn("%s 가 로그인하지 못했습니다. logs/%s.log 를 확인해 주세요." % (bot["name"], bot["id"]))
                elif st["state"] == "offline":
                    warn("%s 가 꺼졌습니다. 상태판에서 다시 켤 수 있어요." % bot["name"])
            last[bot["id"]] = st["state"]
        time.sleep(4)


def main(argv=None) -> int:
    global HUB_PORT
    parser = argparse.ArgumentParser(description="%s 런처" % APP_NAME)
    parser.add_argument("--no-open", dest="open_browser", action="store_false", help="상태판 창을 열지 않습니다")
    parser.add_argument("--stop", action="store_true", help="켜 둔 봇과 상태판을 끕니다")
    parser.add_argument("--update", action="store_true", help="새 버전을 확인하고 지금 업데이트합니다")
    parser.add_argument("--no-update", dest="auto_update", action="store_false", help="업데이트를 확인하지 않습니다")
    parser.add_argument("--no-bots", dest="start_bots", action="store_false", help="봇은 켜지 않고 상태판만 엽니다")
    parser.add_argument("--version", action="store_true", help="버전만 출력합니다")
    parser.add_argument("--hub-port", type=int, default=HUB_PORT)
    parser.set_defaults(open_browser=True, auto_update=True, start_bots=True)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    HUB_PORT = args.hub_port
    if args.version:
        log("v%s" % SERVER_VERSION)
        return 0

    if args.stop:
        return stop_everything()

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if args.update:
        result = apply_update(reason="cli")
        if result.get("ok") and not result.get("uptodate"):
            log("업데이트했습니다. v%s → v%s. 실행하기.bat 을 다시 더블클릭하면 새 버전으로 켜집니다."
                % (result.get("previous"), result.get("version")))
        elif result.get("uptodate"):
            log("이미 최신 버전입니다. (v%s)" % SERVER_VERSION)
        else:
            warn("업데이트하지 못했습니다: %s" % result.get("error"))
        return 0 if result.get("ok") else 1

    if args.auto_update:
        auto_update_at_start()

    print_banner()
    install_console_handlers()

    url = "http://%s:%d/" % (HUB_HOST, args.hub_port)
    already = http_json("http://%s:%d/api/status" % (HUB_HOST, args.hub_port), 0.8)
    if already and already.get("app") == "discord-bots-launcher":
        log("이미 켜져 있는 런처가 있습니다 → " + url)
        log("상태 확인과 켜기/끄기는 상태판에서 하세요.")
        if args.open_browser:
            threading.Timer(0.4, lambda: open_app_window(url)).start()
        time.sleep(1.2)
        return 0

    if args.start_bots:
        log("디스코드 봇을 확인합니다...")
        start_bots()

    hub_ours = start_hub()
    if not hub_ours and not http_json("http://%s:%d/api/status" % (HUB_HOST, args.hub_port), 0.8):
        warn("상태판 없이 봇만 켭니다.")

    write_pid_file()

    if args.open_browser:
        threading.Timer(0.6, lambda: open_app_window(url)).start()

    if args.start_bots:
        threading.Thread(target=wait_bots_ready, name="bots-ready", daemon=True).start()

    print_status_table()
    threading.Thread(target=monitor, name="monitor", daemon=True).start()
    try:
        while not _STOP_EVENT.wait(1.0):
            pass
    except KeyboardInterrupt:
        shutdown_all("Ctrl+C — 봇을 정리하는 중...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
