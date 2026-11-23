# 🎧 백수톡 디코봇 — 료그봇 · 뮤직봇 전용 런처

치현 님 PC에서 **디스코드 봇 두 개를 한 번에 켜고 끄는** 전용 런처입니다.
`실행하기.bat` 하나만 더블클릭하면 봇 두 개가 **까만 콘솔 창 없이** 백그라운드에서 돌고,
작은 **상태판**(`http://127.0.0.1:8771`)이 열립니다.

| 봇 | 하는 일 | 폴더 |
|---|---|---|
| 🛡️ **료그봇** | 백수톡의 사진·파일·삭제·수정·입퇴장·음성 로그를 개인 서버 `paranoia`의 `#백수톡-로그`에 원본 그대로 남김 + 유틸리티 명령어 `/지우개` `/뽑기` `/투표` `/타이머` `/공지` `/사용법` | `tools/log-bot` |
| 🎵 **뮤직봇** | 음성 채널에서 유튜브 곡 재생 — `/r` 재생 · `/s` 스킵 · `/q` 대기열 · `/x` 나가기 | `tools/music-bot` |

> 기존 `discord-log-bot`·`discord-music-bot` 저장소의 코드를 그대로 안에 넣었습니다. 기능은 같고, 켜고 끄는 방식만 편해졌습니다.

---

## 1️⃣ 처음 한 번 (2분)

1. 이 폴더를 `C:\discord-bots-launcher` 처럼 **영문·짧은 경로**에 풉니다.
2. **`실행하기.bat` 더블클릭** — 처음 한 번은 파이썬 패키지(discord.py·yt-dlp·PyNaCl)를 설치하느라 1~3분 걸립니다.
3. 봇 토큰을 넣습니다. **둘 중 편한 방법 하나**면 됩니다.
   - **기존 봇 폴더의 `.env` 를 그대로 복사** → `tools\log-bot\.env`, `tools\music-bot\.env` 에 각각 넣기
   - 또는 상태판 카드의 **`토큰 넣기`** → 기존 `.env` 내용을 통째로(또는 토큰만) 붙여넣기 → **저장하고 켜기**
4. 카드가 **온라인**으로 바뀌면 끝입니다.

토큰은 https://discord.com/developers/applications 에서 봇을 고르고 **Bot → Reset Token** 으로 발급합니다.

- 료그봇 앱: https://discord.com/developers/applications/1572393464576876594/bot
- 뮤직봇 앱: https://discord.com/developers/applications/1572389279139758090/bot

---

## 2️⃣ 평소 쓰는 법

- 켜기: **`실행하기.bat`** (또는 바탕화면의 **백수톡 디코봇** 아이콘)
- 끄기: **`종료하기.bat`**
- 상태판: http://127.0.0.1:8771 — 온라인/오프라인 확인, 봇별 **켜기/끄기**, **로그** 보기, **토큰 바꾸기**
- 상태판 **창을 닫아도 봇은 계속 돕니다.** (까만 창이 안 남는 것과 같은 이유입니다)
- 바탕화면 아이콘: **`바탕화면 바로가기 만들기.bat`** → `백수톡 디코봇.lnk` 생성

부팅할 때 자동으로 켜고 싶으면 `백수톡 디코봇.lnk` 를 `shell:startup` 폴더에 넣어 두면 됩니다.

---

## 3️⃣ 자동 업데이트

- 실행할 때마다 GitHub의 `version.json` 을 **3초만** 확인합니다. (느리거나 오프라인이면 그냥 넘어감)
- 새 버전이 있으면 ZIP을 받아 이 폴더를 덮어쓰고 새 코드로 다시 시작합니다.
- **`.env`(토큰·채널 ID), `logs`, `tools/*/bin`(ffmpeg), `cookies.txt` 는 절대 덮어쓰지 않습니다.**
- 지금 버전: `1.0.5` · `python launcher.py --version`

---

## 4️⃣ 폴더 구조

```
discord-bots-launcher/
  실행하기.bat            봇 2개 + 상태판 켜기 (pythonw · 콘솔 숨김)
  종료하기.bat            봇 + 상태판 끄기
  바탕화면 바로가기 만들기.bat   → 백수톡 디코봇.lnk
  launcher.py             봇 관리 + 상태판(8771) + 자동 업데이트
  index.html app.js style.css   상태판 화면
  version.json            버전·업데이트 정보
  requirements.txt        discord.py[voice] · yt-dlp · PyNaCl · python-dotenv · aiohttp · imageio-ffmpeg
  assets/app.ico          바탕화면 아이콘
  tools/log-bot/          료그봇 (bot.py · logfmt.py · .env)
  tools/music-bot/        뮤직봇 (bot.py · .env)
  logs/                   실행 로그 (launcher.log · log-bot.log · music-bot.log)
```

---

## 5️⃣ 자주 묻는 문제

**"토큰 미설정"으로 표시돼요**
`tools\log-bot\.env`(또는 `tools\music-bot\.env`)가 없거나 `DISCORD_TOKEN=` 이 비어 있는 상태입니다. 상태판의 **토큰 넣기**로 한 번만 저장하면 다음부터 자동으로 켜집니다.

**"오류"로 표시돼요**
카드의 **로그**를 보세요. `Improper token` 이면 토큰이 재발급되어 예전 값이 무효가 된 것입니다 → **토큰 바꾸기**.
`No module named ...` 이면 **`실행하기.bat`** 을 다시 실행해 패키지를 설치하세요.

**뮤직봇에서 소리가 안 나요**
PC에 이미 있는 ffmpeg(`PATH` 또는 `tools\music-bot\bin`)를 먼저 쓰고, 없으면 `imageio-ffmpeg` 가 함께 설치한 ffmpeg를 씁니다. 그래도 안 되면 `tools\music-bot\bin\ffmpeg.exe` 에 직접 넣어 주세요.

**예전 폴더에서 돌던 봇이랑 같이 켜지나요?**
같은 토큰으로 두 번 로그인하면 하나가 끊깁니다. 예전 폴더의 봇 창은 닫고 이 런처만 쓰세요.

**포트 8771이 이미 쓰인다고 나와요**
런처가 이미 떠 있는 상태입니다. 상태판 창을 열면 됩니다. (`종료하기.bat` 으로 한 번 정리해도 됩니다)

---

## 6️⃣ 원본 저장소

- 로그봇 코드: https://github.com/anchirong9-arch/discord-log-bot
- 뮤직봇 코드: https://github.com/anchirong9-arch/discord-music-bot
- 이 런처: https://github.com/anchirong9-arch/discord-bots-launcher
- 릴리스 ZIP: https://github.com/anchirong9-arch/discord-bots-launcher/releases/latest/download/discord-bots-launcher.zip

Python 3.9 이상. 토큰은 이 PC의 `.env` 에만 저장되고 저장소에는 올라가지 않습니다.
