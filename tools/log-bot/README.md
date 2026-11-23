# 🛡️ 료그봇 (백수톡 로그봇)

**백수톡** 서버에서 일어나는 일을, 치현 님 개인 서버 `paranoia` 의 비공개 **`#백수톡-로그`** 채널에 남깁니다.
사진·파일은 **원본 그대로 다시 첨부**해서, 원래 방에서 메시지를 지워도 로그 방에는 남습니다.

> 이 폴더는 런처(`백수톡 디코봇`)가 자동으로 켭니다. 여기서 직접 `python bot.py` 로 켜도 됩니다.

## 설정 (`.env`)

```ini
DISCORD_TOKEN=봇_토큰
SOURCE_GUILD_ID=386882960403726337      # 감시할 서버: 백수톡
LOG_CHANNEL_ID=1572394445142360064      # 남길 채널: paranoia #백수톡-로그
LOG_USER_ID=                            # (선택) 디엠 사본
```

- 토큰: https://discord.com/developers/applications/1572393464576876594/bot → **Reset Token**
- 초대: https://discord.com/oauth2/authorize?client_id=1572393464576876594&permissions=117888&integration_type=0&scope=bot
  (백수톡 + paranoia 두 서버에 각각 초대)

## 남기는 것

사진·파일 원본 · 메시지 삭제(본문·첨부까지) · 수정 전/후 · 입장 · 퇴장/추방 · 차단 · 닉네임/역할 변경 ·
음성 채널 입퇴장·마이크/화면공유 상태 · 채널 생성/삭제/변경 · 역할 변경.
봇 자신의 메시지와 `#백수톡-로그` 안의 메시지는 기록하지 않습니다.

원본 코드: https://github.com/anchirong9-arch/discord-log-bot
