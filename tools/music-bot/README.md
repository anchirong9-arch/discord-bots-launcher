# 🎵 뮤직봇 (안치롱 뮤직봇)

디스코드 음성 채널에서 **유튜브 노래를 틀어 주는 봇**입니다.

> 이 폴더는 런처(`백수톡 디코봇`)가 자동으로 켭니다. 여기서 직접 `python bot.py` 로 켜도 됩니다.

## 설정 (`.env`)

```ini
DISCORD_TOKEN=봇_토큰
```

- 토큰: https://discord.com/developers/applications/1572389279139758090/bot → **Reset Token**
- 초대: https://discord.com/oauth2/authorize?client_id=1572389279139758090&permissions=3165184&integration_type=0&scope=bot+applications.commands
- FFmpeg: 런처가 `imageio-ffmpeg` 로 설치한 ffmpeg 를 자동으로 넘겨 줍니다. 직접 넣으려면 `bin\ffmpeg.exe` 에 두면 됩니다.

## 명령어

| 명령어 | 설명 |
|---|---|
| `/r <유튜브 링크 또는 검색어>` | 곡 재생 (대기열에 추가) |
| `/s` | 스킵 |
| `/q` | 대기열 보기 |
| `/x` | 정지 + 대기열 비우고 음성 채널 나가기 |
| `/일시정지` `/재개` `/현재곡` | 보조 명령어 |

명령을 쓰려면 **먼저 음성 채널에 들어가 있어야** 합니다. 곡이 끝나면 대기열의 다음 곡이 자동으로 재생됩니다.

원본 코드: https://github.com/anchirong9-arch/discord-music-bot
