"""백수톡 서버 로그 봇.

서버에서 일어나는 일을 #서버-로그 같은 비공개 채널에 차곡차곡 남긴다.
사진·파일은 **원본 그대로** 다시 첨부해서, 원래 방에서 메시지를 지워도
로그 방에는 남아 있게 한다.

실행:  python bot.py
설정:  .env 파일의 DISCORD_TOKEN / LOG_CHANNEL_ID / LOG_USER_ID
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import discord
from discord import app_commands
from dotenv import load_dotenv

import logfmt

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("logbot")

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
# 감시할 서버: 백수톡. 이 서버에서 일어난 일만 기록한다.
SOURCE_GUILD_ID = int(os.getenv("SOURCE_GUILD_ID", "386882960403726337").strip() or 0)
# 로그를 쌓을 채널: 개인 서버(paranoia)의 #백수톡-로그
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "1572394445142360064").strip() or 0)
# 선택: 로그를 디엠으로도 받을 사용자 ID (0 이면 끔)
LOG_USER_ID = int(os.getenv("LOG_USER_ID", "0").strip() or 0)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 디스코드 기본 업로드 한도
MAX_FILES_PER_MESSAGE = 10
CACHE_MAX_FILES = 300
CACHE_MAX_BYTES = 300 * 1024 * 1024

COLOR = {
    "attachment": 0x5865F2,
    "delete": 0xED4245,
    "edit": 0xFEE75C,
    "join": 0x57F287,
    "leave": 0x95A5A6,
    "ban": 0xEB459E,
    "voice": 0x1ABC9C,
    "channel": 0xE67E22,
    "role": 0x9B59B6,
    "member": 0x3498DB,
    "system": 0x5865F2,
}

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".avif")

# 유틸리티 명령어 공통 색 — 라일락 보라
PURPLE = 0xC084FC
# 명령어를 마지막으로 디스코드에 등록한 흔적 (내용이 바뀔 때만 다시 등록)
SYNC_MARKER = Path(__file__).resolve().parent / ".command-sync.json"
VENUE = "백수톡"


# ---------------------------------------------------------------------------
# 임베드 만들기 (디스코드 연결 없이도 테스트 가능한 순수 함수들)
# ---------------------------------------------------------------------------

def _user_text(user) -> str:
    name = getattr(user, "display_name", None) or getattr(user, "name", None) or "알 수 없음"
    user_id = getattr(user, "id", "?")
    return f"{name} ({user_id})"


def _channel_text(channel) -> str:
    if channel is None:
        return "알 수 없는 채널"
    name = getattr(channel, "name", None) or "이름 없음"
    return f"#{name} ({getattr(channel, 'id', '?')})"


def _guild_name(message_or_guild) -> str:
    guild = getattr(message_or_guild, "guild", None) or message_or_guild
    return getattr(guild, "name", "백수톡")


def from_source_guild(obj, source_id: int = None) -> bool:
    """이 객체가 감시 대상 서버(기본: 백수톡)의 것인지.

    봇이 여러 서버에 들어가 있으므로, 로그 방이 있는 개인 서버에서 일어난 일은
    기록하지 않고 백수톡에서 일어난 일만 남긴다.
    """
    target = SOURCE_GUILD_ID if source_id is None else source_id
    if not target:
        return True
    guild = getattr(obj, "guild", None)
    return getattr(guild, "id", None) == target


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _footer(embed: discord.Embed, guild_name: str, tail: str = "") -> discord.Embed:
    text = f"{guild_name}"
    if tail:
        text = f"{text} · {tail}"
    embed.set_footer(text=text[:2048])
    return embed


def build_attachment_embed(message, saved, skipped) -> discord.Embed:
    """사진·파일이 올라왔을 때 남기는 로그."""
    guild_name = _guild_name(message)
    embed = discord.Embed(
        title="📎 사진·파일 원본 보존",
        colour=COLOR["attachment"],
        timestamp=getattr(message, "created_at", None) or _now(),
    )
    embed.add_field(name="작성자", value=logfmt.shorten(_user_text(message.author), 256), inline=True)
    embed.add_field(name="채널", value=logfmt.shorten(_channel_text(getattr(message, "channel", None)), 256), inline=True)

    content = logfmt.shorten(getattr(message, "content", None), 1000)
    embed.add_field(name="메시지", value=content, inline=False)

    if saved:
        lines = [f"`{name}` · {logfmt.format_size(size)}" for name, size in saved]
        embed.add_field(name="원본으로 보관한 파일", value=logfmt.shorten("\n".join(lines), 1000), inline=False)

    if skipped:
        lines = [
            f"`{getattr(a, 'filename', '파일')}` · {logfmt.format_size(getattr(a, 'size', None))}"
            for a in skipped
        ]
        embed.add_field(
            name="원본 보관 실패 (25MB 초과)",
            value=logfmt.shorten("\n".join(lines) + "\n원본 링크로만 남겨 둡니다.", 1000),
            inline=False,
        )

    url = logfmt.jump_url(
        getattr(getattr(message, "guild", None), "id", "@me"),
        getattr(getattr(message, "channel", None), "id", 0),
        getattr(message, "id", 0),
    )
    embed.add_field(name="원본 메시지", value=f"[바로가기]({url})", inline=False)
    return _footer(embed, guild_name, f"메시지 {getattr(message, 'id', '?')}")


def build_delete_embed(message, attachment_names) -> discord.Embed:
    """메시지가 삭제됐을 때 남기는 로그."""
    guild_name = _guild_name(message)
    embed = discord.Embed(
        title="🗑️ 메시지 삭제됨",
        colour=COLOR["delete"],
        timestamp=_now(),
    )
    embed.add_field(name="작성자", value=logfmt.shorten(_user_text(getattr(message, "author", None)), 256), inline=True)
    embed.add_field(name="채널", value=logfmt.shorten(_channel_text(getattr(message, "channel", None)), 256), inline=True)
    embed.add_field(
        name="삭제 전 내용",
        value=logfmt.shorten(getattr(message, "content", None), 1000),
        inline=False,
    )
    if attachment_names:
        embed.add_field(
            name="첨부돼 있던 파일",
            value=logfmt.shorten(", ".join(f"`{n}`" for n in attachment_names), 1000),
            inline=False,
        )
    created = getattr(message, "created_at", None)
    if created:
        embed.add_field(name="원래 작성 시각", value=discord.utils.format_dt(created, "F"), inline=False)
    return _footer(embed, guild_name, f"메시지 {getattr(message, 'id', '?')}")


def build_edit_embed(before, after) -> discord.Embed:
    """메시지가 수정됐을 때 남기는 로그."""
    guild_name = _guild_name(after)
    embed = discord.Embed(
        title="✏️ 메시지 수정됨",
        colour=COLOR["edit"],
        timestamp=_now(),
    )
    embed.add_field(name="작성자", value=logfmt.shorten(_user_text(getattr(after, "author", None)), 256), inline=True)
    embed.add_field(name="채널", value=logfmt.shorten(_channel_text(getattr(after, "channel", None)), 256), inline=True)
    embed.add_field(name="수정 전", value=logfmt.shorten(getattr(before, "content", None), 1000), inline=False)
    embed.add_field(name="수정 후", value=logfmt.shorten(getattr(after, "content", None), 1000), inline=False)

    url = logfmt.jump_url(
        getattr(getattr(after, "guild", None), "id", "@me"),
        getattr(getattr(after, "channel", None), "id", 0),
        getattr(after, "id", 0),
    )
    embed.add_field(name="메시지", value=f"[바로가기]({url})", inline=False)
    return _footer(embed, guild_name, f"메시지 {getattr(after, 'id', '?')}")


def build_member_join_embed(member) -> discord.Embed:
    guild_name = getattr(getattr(member, "guild", None), "name", "백수톡")
    embed = discord.Embed(
        title="✅ 멤버 입장",
        description=f"{logfmt.shorten(_user_text(member), 256)} 님이 들어왔어요.",
        colour=COLOR["join"],
        timestamp=_now(),
    )
    created = getattr(member, "created_at", None)
    if created:
        embed.add_field(name="계정 만든 날", value=discord.utils.format_dt(created, "F"), inline=True)
    count = getattr(getattr(member, "guild", None), "member_count", None)
    if count:
        embed.add_field(name="현재 멤버 수", value=f"{count}명", inline=True)
    return _footer(embed, guild_name, f"사용자 {getattr(member, 'id', '?')}")


def build_member_leave_embed(member) -> discord.Embed:
    guild_name = getattr(getattr(member, "guild", None), "name", "백수톡")
    embed = discord.Embed(
        title="👋 멤버 퇴장",
        description=f"{logfmt.shorten(_user_text(member), 256)} 님이 나갔어요(또는 추방됐어요).",
        colour=COLOR["leave"],
        timestamp=_now(),
    )
    joined = getattr(member, "joined_at", None)
    if joined:
        embed.add_field(name="서버에 들어온 날", value=discord.utils.format_dt(joined, "F"), inline=False)
    roles = [r.name for r in getattr(member, "roles", []) if getattr(r, "name", None) != "@everyone"]
    if roles:
        embed.add_field(name="가지고 있던 역할", value=logfmt.shorten(", ".join(roles), 1000), inline=False)
    return _footer(embed, guild_name, f"사용자 {getattr(member, 'id', '?')}")


def build_member_ban_embed(guild, user) -> discord.Embed:
    guild_name = getattr(guild, "name", "백수톡")
    embed = discord.Embed(
        title="🚫 멤버 차단(밴)",
        description=f"{logfmt.shorten(_user_text(user), 256)} 님이 서버에서 차단됐어요.",
        colour=COLOR["ban"],
        timestamp=_now(),
    )
    return _footer(embed, guild_name, f"사용자 {getattr(user, 'id', '?')}")


def build_voice_embed(member, kind, description) -> discord.Embed:
    guild_name = getattr(getattr(member, "guild", None), "name", "백수톡")
    embed = discord.Embed(
        title=f"🎧 음성 {kind}",
        description=logfmt.shorten(description, 1000),
        colour=COLOR["voice"],
        timestamp=_now(),
    )
    embed.add_field(name="멤버", value=logfmt.shorten(_user_text(member), 256), inline=False)
    return _footer(embed, guild_name, f"사용자 {getattr(member, 'id', '?')}")


def _channel_type_name(channel) -> str:
    ctype = getattr(channel, "type", None)
    name = getattr(ctype, "name", None) or str(ctype)
    return {
        "text": "텍스트 채널",
        "voice": "음성 채널",
        "category": "카테고리",
        "news": "공지 채널",
        "forum": "포럼",
        "stage": "스테이지",
    }.get(name, name)


def build_channel_embed(kind, channel, changes: Optional[Iterable[str]] = None) -> discord.Embed:
    guild_name = getattr(getattr(channel, "guild", None), "name", "백수톡")
    title = {"생성": "📁 채널 생성", "삭제": "📂 채널 삭제", "변경": "🔧 채널 설정 변경"}[kind]
    colour = COLOR["channel"]
    embed = discord.Embed(title=title, colour=colour, timestamp=_now())
    embed.add_field(name="채널", value=logfmt.shorten(_channel_text(channel), 256), inline=True)
    embed.add_field(name="종류", value=_channel_type_name(channel), inline=True)
    category = getattr(channel, "category", None)
    if category:
        embed.add_field(name="카테고리", value=logfmt.shorten(str(getattr(category, "name", category)), 256), inline=True)
    if changes:
        embed.add_field(name="바뀐 것", value=logfmt.shorten("\n".join(changes), 1000), inline=False)
    return _footer(embed, guild_name, f"채널 {getattr(channel, 'id', '?')}")


def build_role_embed(kind, role, changes: Optional[Iterable[str]] = None) -> discord.Embed:
    guild_name = getattr(getattr(role, "guild", None), "name", "백수톡")
    title = {"생성": "🎭 역할 생성", "삭제": "🎭 역할 삭제", "변경": "🎭 역할 변경"}[kind]
    embed = discord.Embed(title=title, colour=COLOR["role"], timestamp=_now())
    embed.add_field(name="역할", value=f"{getattr(role, 'name', '?')} ({getattr(role, 'id', '?')})", inline=True)
    members = getattr(role, "members", None)
    if members is not None:
        try:
            embed.add_field(name="멤버 수", value=f"{len(members)}명", inline=True)
        except TypeError:
            pass
    if changes:
        embed.add_field(name="바뀐 것", value=logfmt.shorten("\n".join(changes), 1000), inline=False)
    return _footer(embed, guild_name, f"역할 {getattr(role, 'id', '?')}")


def build_member_update_embed(before, after, changes: Iterable[str]) -> discord.Embed:
    guild_name = getattr(getattr(after, "guild", None), "name", "백수톡")
    embed = discord.Embed(title="👤 멤버 정보 변경", colour=COLOR["member"], timestamp=_now())
    embed.add_field(name="멤버", value=logfmt.shorten(_user_text(after), 256), inline=False)
    embed.add_field(name="바뀐 것", value=logfmt.shorten("\n".join(changes), 1000), inline=False)
    return _footer(embed, guild_name, f"사용자 {getattr(after, 'id', '?')}")


def permission_diff(before, after) -> list[str]:
    """역할 권한에서 켜지고 꺼진 것만 뽑는다."""
    lines = []
    old = logfmt.permission_names(getattr(before, "permissions", None))
    new = logfmt.permission_names(getattr(after, "permissions", None))
    added = [p for p in new if p not in old]
    removed = [p for p in old if p not in new]
    if added:
        lines.append("권한 켜짐: " + ", ".join(added))
    if removed:
        lines.append("권한 꺼짐: " + ", ".join(removed))
    return lines


# ---------------------------------------------------------------------------
# 유틸리티 명령어 (/지우개 /뽑기 /투표 /타이머 /공지 /사용법)
#   — 임베드는 디스코드 연결 없이도 만들 수 있게 순수 함수로 둔다.
# ---------------------------------------------------------------------------

BAR_FULL = "█"
BAR_EMPTY = "░"
MAX_VOTE_OPTIONS = 5
MAX_PICK_ITEMS = 25
VOTE_SECONDS = 3600  # 투표 버튼을 받아 두는 시간 (1시간)


def _bar(ratio: float, width: int = 12) -> str:
    filled = int(round(max(0.0, min(1.0, ratio)) * width))
    return BAR_FULL * filled + BAR_EMPTY * (width - filled)


def split_items(text: str, limit: int = MAX_PICK_ITEMS) -> list[str]:
    """`사과, 배 , 감` 처럼 쉼표(또는 줄바꿈)로 적은 항목을 깔끔하게 나눈다."""
    raw = (text or "").replace("\r", "").replace("\n", ",")
    items = [part.strip() for part in raw.split(",")]
    return [item for item in items if item][:limit]


def build_pick_embed(pool: list[str], picked: str) -> discord.Embed:
    embed = discord.Embed(title="🎲 뽑기 결과", colour=PURPLE, timestamp=_now())
    embed.add_field(name="뽑힌 항목", value=logfmt.shorten(picked, 256), inline=False)
    embed.add_field(
        name=f"후보 {len(pool)}개",
        value=logfmt.shorten(", ".join(pool), 1000),
        inline=False,
    )
    embed.set_footer(text=f"{VENUE} · 후보 {len(pool)}개 중 1개")
    return embed


def build_team_embed(team1: list[str], team2: list[str]) -> discord.Embed:
    embed = discord.Embed(title="🎲 팀 나누기", colour=PURPLE, timestamp=_now())
    embed.add_field(
        name=f"1팀 ({len(team1)}명)",
        value=logfmt.shorten("\n".join(f"· {name}" for name in team1) or "—", 1000),
        inline=True,
    )
    embed.add_field(
        name=f"2팀 ({len(team2)}명)",
        value=logfmt.shorten("\n".join(f"· {name}" for name in team2) or "—", 1000),
        inline=True,
    )
    embed.set_footer(text=f"{VENUE} · {len(team1) + len(team2)}명을 절반씩 나눴어요")
    return embed


def vote_counts(options: list[str], votes: dict) -> list[int]:
    counts = [0] * len(options)
    for index in (votes or {}).values():
        if isinstance(index, int) and 0 <= index < len(options):
            counts[index] += 1
    return counts


def build_vote_embed(question: str, options: list[str], votes: dict, closed: bool = False) -> discord.Embed:
    counts = vote_counts(options, votes)
    total = sum(counts)
    lines = []
    for index, option in enumerate(options):
        ratio = (counts[index] / total) if total else 0.0
        lines.append(f"`{_bar(ratio)}` **{counts[index]}표** ({ratio * 100:.0f}%) · {option}")
    embed = discord.Embed(
        title="🗳️ 투표 — 마감" if closed else "🗳️ 투표",
        description=logfmt.shorten(f"**{question}**", 2000),
        colour=PURPLE,
        timestamp=_now(),
    )
    embed.add_field(
        name="결과" if total else "아직 표가 없어요 — 버튼을 눌러 주세요",
        value=logfmt.shorten("\n".join(lines), 1024),
        inline=False,
    )
    tail = f"총 {total}표 · 1인 1표" + ("" if closed else f" · {VOTE_SECONDS // 60}분 뒤 자동 마감")
    embed.set_footer(text=f"{VENUE} · {tail}")
    return embed


def format_minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}분"
    hours, rest = divmod(minutes, 60)
    return f"{hours}시간 {rest}분" if rest else f"{hours}시간"


def build_timer_start_embed(minutes: int, memo: str, when: datetime) -> discord.Embed:
    embed = discord.Embed(
        title="⏰ 타이머 시작",
        description=logfmt.shorten(memo, 1000) if memo else "시간이 다 되면 이 채널에서 알려 드릴게요.",
        colour=PURPLE,
        timestamp=_now(),
    )
    embed.add_field(name="알림까지", value=format_minutes(minutes), inline=True)
    embed.add_field(name="알림 시각", value=discord.utils.format_dt(when, "t"), inline=True)
    embed.set_footer(text=f"{VENUE} · 봇을 끄면 타이머도 사라져요")
    return embed


def build_timer_alert_embed(minutes: int, memo: str) -> discord.Embed:
    embed = discord.Embed(
        title="⏰ 타이머 끝!",
        description=logfmt.shorten(memo, 1000) if memo else "설정한 시간이 다 됐어요.",
        colour=PURPLE,
        timestamp=_now(),
    )
    embed.set_footer(text=f"{VENUE} · {format_minutes(minutes)} 타이머")
    return embed


def build_notice_embed(title: str, content: str, author=None) -> discord.Embed:
    body = (content or "").replace("\\n", "\n")
    embed = discord.Embed(
        title=logfmt.shorten(f"📢 {title}", 256),
        description=logfmt.shorten(body, 4000),
        colour=PURPLE,
        timestamp=_now(),
    )
    if author is not None:
        name = getattr(author, "display_name", None) or getattr(author, "name", None)
        if name:
            embed.set_author(name=name, icon_url=getattr(getattr(author, "display_avatar", None), "url", None))
    embed.set_footer(text=f"{VENUE} 공지")
    return embed


USAGE_ROWS = [
    (
        "/지우개 개수:10",
        "이 채널의 최근 메시지를 지웁니다. (1~100, 기본 10)\n"
        "**예:** `/지우개 개수:20`",
    ),
    (
        "/뽑기 항목:치킨,피자,족발 [팀나누기:True]",
        "쉼표로 나눈 항목 중 하나를 뽑습니다. `팀나누기:True` 면 절반씩 1팀·2팀으로 나눠요.\n"
        "**예:** `/뽑기 항목:철수,영희,민수,지수 팀나누기:True`",
    ),
    (
        "/투표 질문:오늘 저녁? 선택지:치킨,피자,족발",
        "버튼 투표를 엽니다. 선택지는 2~5개, 1인 1표이고 다른 버튼을 누르면 표가 옮겨져요. "
        f"{VOTE_SECONDS // 60}분 뒤 자동 마감.",
    ),
    (
        "/타이머 분:25 메모:라면 불 끄기",
        "정한 시간이 지나면 이 채널에서 알려 줍니다. (1~180분, 메모는 선택)",
    ),
    (
        "/공지 제목:서버 규칙 내용:1. 욕설 금지\\n2. 광고 금지",
        "보라색 공지 박스를 이 채널에 올립니다. `\\n` 으로 줄을 바꿀 수 있어요.",
    ),
]

USAGE_CAUTIONS = (
    "• `/지우개` 는 **2주(14일)가 지난 메시지**를 디스코드 정책상 일괄로 지울 수 없어 일부가 남을 수 있어요.\n"
    "• `/지우개` 는 실행한 사람과 봇 모두에게 **메시지 관리** 권한이 있어야 하고, 고정(핀)한 메시지도 함께 지워져요.\n"
    "• `/투표` 버튼은 1시간이 지나면 자동으로 닫히고, 봇을 다시 켜면 진행 중이던 투표 버튼은 눌리지 않아요.\n"
    "• `/타이머` 는 봇이 켜져 있는 동안만 알려 줍니다."
)


def build_usage_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🤖 료그봇 사용법 — 유틸리티 명령어",
        description="앞에 `/` 를 붙여 쓰면 됩니다. 디스코드 입력창에 `/` 만 쳐도 목록이 떠요.",
        colour=PURPLE,
    )
    for name, description in USAGE_ROWS:
        embed.add_field(name=name, value=logfmt.shorten(description, 1000), inline=False)
    embed.add_field(name="주의사항", value=USAGE_CAUTIONS, inline=False)
    embed.set_footer(text=f"{VENUE} · 로그 기록 기능은 그대로 돌아가요")
    return embed


class VoteView(discord.ui.View):
    """`/투표` 버튼 — 한 사람 한 표, 다른 버튼을 누르면 표가 옮겨진다."""

    def __init__(self, question: str, options: list[str], timeout: Optional[float] = VOTE_SECONDS):
        super().__init__(timeout=timeout)
        self.question = question
        self.options = options
        self.votes: dict[int, int] = {}
        self.closed = False
        for index, option in enumerate(options):
            self.add_item(VoteButton(index, option))

    def embed(self, closed: Optional[bool] = None) -> discord.Embed:
        return build_vote_embed(
            self.question,
            self.options,
            self.votes,
            closed=self.closed if closed is None else closed,
        )

    async def on_timeout(self) -> None:
        self.closed = True
        for item in self.children:
            item.disabled = True
        message = getattr(self, "message", None)
        if message is None:
            return
        try:
            await message.edit(embed=self.embed(closed=True), view=self)
        except Exception:
            log.warning("투표 마감 표시 실패", exc_info=True)


class VoteButton(discord.ui.Button):
    def __init__(self, index: int, label: str):
        super().__init__(
            label=logfmt.shorten(label, 80),
            style=discord.ButtonStyle.primary,
            custom_id=f"vote:{index}",
            row=0,
        )
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        view: VoteView = self.view
        if view is None or view.closed:
            await interaction.response.send_message("이 투표는 이미 마감됐어요.", ephemeral=True)
            return
        current = view.votes.get(interaction.user.id)
        if current == self.index:
            await interaction.response.send_message(
                "이미 이 항목에 투표했어요. 다른 항목을 누르면 표가 옮겨져요.", ephemeral=True
            )
            return
        view.votes[interaction.user.id] = self.index
        await interaction.response.edit_message(embed=view.embed(), view=view)


async def _reply(interaction: discord.Interaction, text: str) -> None:
    """이미 응답했으면 followup 으로, 아니면 ephemeral 응답으로 안내한다."""
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


def command_signature(tree: app_commands.CommandTree) -> str:
    parts = []
    for command in sorted(tree.get_commands(), key=lambda c: c.name):
        params = ",".join(f"{p.name}:{p.required}" for p in command.parameters)
        parts.append(f"{command.name}({params})")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def register_commands(bot: "LogBot") -> None:
    """유틸리티 슬래시 명령어 6종을 봇의 명령어 트리에 붙인다."""

    @app_commands.command(name="지우개", description="이 채널의 최근 메시지를 지웁니다 (최대 100개)")
    @app_commands.rename(count="개수")
    @app_commands.describe(count="지울 메시지 수 (1~100, 기본 10)")
    @app_commands.guild_only()
    async def erase(interaction: discord.Interaction, count: app_commands.Range[int, 1, 100] = 10) -> None:
        channel = interaction.channel
        if interaction.guild is None or not isinstance(
            channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.Thread)
        ):
            await _reply(interaction, "이 채널에서는 `/지우개` 를 쓸 수 없어요. 일반 텍스트 채널에서 써 주세요.")
            return

        member_perms = channel.permissions_for(interaction.user)
        if not (member_perms.manage_messages or member_perms.administrator):
            await _reply(
                interaction,
                "`/지우개` 는 **메시지 관리** 권한이 있는 사람만 쓸 수 있어요.\n"
                "서버 관리자에게 권한을 요청해 주세요.",
            )
            return

        bot_perms = channel.permissions_for(interaction.guild.me)
        missing = []
        if not bot_perms.manage_messages:
            missing.append("메시지 관리")
        if not bot_perms.read_message_history:
            missing.append("메시지 기록 읽기")
        if missing:
            await _reply(
                interaction,
                "봇에게 권한이 없어서 지울 수 없어요.\n"
                f"필요한 권한: {', '.join('**' + name + '**' for name in missing)}\n"
                "서버 설정 → 역할 → 봇 역할에서 켜 주세요.",
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        bot.suppress_delete_logs(channel.id)
        try:
            deleted = await channel.purge(limit=int(count))
        except discord.Forbidden:
            await _reply(
                interaction,
                "디스코드가 삭제를 거부했어요. 봇 역할이 이 채널보다 위에 있는지, "
                "**메시지 관리** 권한이 있는지 확인해 주세요.",
            )
            return
        except discord.HTTPException as exc:
            await _reply(interaction, f"삭제하다가 문제가 생겼어요: `{exc}`")
            return

        text = f"🧹 이 채널의 최근 메시지 **{len(deleted)}개**를 지웠어요."
        if len(deleted) < int(count):
            text += (
                f"\n요청은 {count}개였는데, 이미 지워졌거나 2주가 지나 일괄 삭제가 안 되는 메시지는 남았어요."
            )
        await _reply(interaction, text)

    @app_commands.command(name="뽑기", description="항목 중 하나를 뽑거나 팀을 나눕니다")
    @app_commands.rename(items="항목", split="팀나누기")
    @app_commands.describe(
        items="쉼표(,)로 구분한 항목들 (2개 이상)",
        split="True 면 절반씩 1팀·2팀으로 나눕니다",
    )
    async def draw(interaction: discord.Interaction, items: str, split: bool = False) -> None:
        pool = split_items(items)
        if len(pool) < 2:
            await _reply(
                interaction,
                "항목을 쉼표(`,`)로 구분해 **2개 이상** 적어 주세요.\n"
                "예: `/뽑기 항목:치킨,피자,족발`",
            )
            return
        if split:
            shuffled = pool[:]
            random.shuffle(shuffled)
            half = (len(shuffled) + 1) // 2
            embed = build_team_embed(shuffled[:half], shuffled[half:])
        else:
            embed = build_pick_embed(pool, random.choice(pool))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="투표", description="2~5개 선택지로 버튼 투표를 엽니다")
    @app_commands.rename(question="질문", options="선택지")
    @app_commands.describe(question="투표할 질문", options="쉼표(,)로 구분한 2~5개 선택지")
    async def vote(interaction: discord.Interaction, question: str, options: str) -> None:
        choices = split_items(options, limit=MAX_VOTE_OPTIONS)
        if len(choices) < 2:
            await _reply(
                interaction,
                "선택지는 쉼표(`,`)로 구분해 **2~5개** 적어 주세요.\n"
                "예: `/투표 질문:오늘 저녁 뭐 먹지? 선택지:치킨,피자,족발`",
            )
            return
        view = VoteView(question=question, options=choices)
        await interaction.response.send_message(embed=view.embed(), view=view)
        try:
            view.message = await interaction.original_response()
        except Exception:
            log.warning("투표 메시지를 잡지 못했습니다", exc_info=True)

    @app_commands.command(name="타이머", description="정한 시간이 지나면 이 채널에서 알려 줍니다")
    @app_commands.rename(minutes="분", memo="메모")
    @app_commands.describe(minutes="몇 분 뒤에 알려 줄지 (1~180)", memo="무엇을 알려 줄지 (선택)")
    async def timer(
        interaction: discord.Interaction,
        minutes: app_commands.Range[int, 1, 180],
        memo: Optional[str] = None,
    ) -> None:
        channel = interaction.channel
        if channel is None or not hasattr(channel, "send"):
            await _reply(interaction, "채널에서만 쓸 수 있어요.")
            return
        note = (memo or "").strip()
        when = _now() + timedelta(minutes=int(minutes))
        await interaction.response.send_message(embed=build_timer_start_embed(int(minutes), note, when))
        bot.start_timer(channel, interaction.user, int(minutes), note)

    @app_commands.command(name="공지", description="보라색 공지 박스를 이 채널에 올립니다")
    @app_commands.rename(title="제목", content="내용")
    @app_commands.describe(title="공지 제목", content="공지 내용 (`\\n` 으로 줄바꿈)")
    async def notice(interaction: discord.Interaction, title: str, content: str) -> None:
        embed = build_notice_embed(title, content, interaction.user)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="사용법", description="료그봇 유틸리티 명령어 사용법을 보여 줍니다")
    async def usage(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_usage_embed(), ephemeral=True)

    for command in (erase, draw, vote, timer, notice, usage):
        bot.tree.add_command(command)


# ---------------------------------------------------------------------------
# 봇 본체
# ---------------------------------------------------------------------------

@dataclass
class LogItem:
    embed: discord.Embed
    files: list = field(default_factory=list)
    image_name: Optional[str] = None


class LogBot(discord.Client):
    def __init__(self, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.voice_states = True
        intents.guilds = True
        intents.moderation = True
        super().__init__(intents=intents, **kwargs)
        # 슬래시 명령어 트리 (discord.Client 는 자동으로 만들지 않아 직접 붙인다)
        self.tree: app_commands.CommandTree = app_commands.CommandTree(self)
        self.queue: "asyncio.Queue[LogItem]" = asyncio.Queue()
        self.cache = logfmt.AttachmentCache(CACHE_MAX_FILES, CACHE_MAX_BYTES)
        self.log_channel: Optional[discord.abc.Messageable] = None
        self.dm_user: Optional[discord.User] = None
        self._sender_task: Optional[asyncio.Task] = None
        self._timers: set = set()
        self._purge_suppress: dict[int, float] = {}

    # -- 시작 ---------------------------------------------------------------

    async def setup_hook(self) -> None:
        register_commands(self)
        self._sender_task = asyncio.create_task(self._sender(), name="log-sender")
        if os.getenv("PORT"):
            asyncio.create_task(_start_health_server(), name="health-server")

    async def on_ready(self) -> None:
        await self._resolve_targets()
        channel = self.log_channel
        where = getattr(channel, "name", "?") if channel else "아직 못 찾음"
        log.info("로그인 완료: %s (서버 %d곳)", self.user, len(self.guilds))
        log.info("감시할 서버: %s", SOURCE_GUILD_ID)
        log.info("로그를 보낼 채널: #%s (%s)", where, LOG_CHANNEL_ID)
        if SOURCE_GUILD_ID and self.get_guild(SOURCE_GUILD_ID) is None:
            log.warning("감시 대상 서버(%s)에 봇이 없습니다. 초대 링크로 봇을 초대해 주세요.", SOURCE_GUILD_ID)
        if LOG_USER_ID:
            log.info("디엠 사본: 사용자 ID %s", LOG_USER_ID)
        await self._sync_commands()

    async def _sync_commands(self) -> None:
        """슬래시 명령어를 디스코드에 등록한다.

        명령어 구성이 그저껄과 같으면 건너뜀(디스코드 등록 제한에 부딪히지 않게).
        다시 강제로 등록하려면 tools/log-bot/.command-sync.json 을 지우고 재시작.
        """
        names = ", ".join("/" + command.name for command in self.tree.get_commands())
        signature = command_signature(self.tree)
        try:
            saved = json.loads(SYNC_MARKER.read_text(encoding="utf-8")).get("signature")
        except Exception:
            saved = None
        if saved == signature:
            log.info("슬래시 명령어 %d건 — 이미 등록된 구성이라 건너뜁니다 (%s)", len(self.tree.get_commands()), names)
            return
        try:
            synced = await self.tree.sync()
        except discord.HTTPException as exc:
            log.warning("슬래시 명령어 등록 실패(%s) — 다음 실행에서 다시 시도합니다", exc)
            return
        log.info("슬래시 명령어 %d건 등록 완료: %s", len(synced), names)
        for guild in list(self.guilds):
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                log.info("'%s' 서버에는 바로 반영했습니다", guild.name)
            except Exception:
                log.warning("'%s' 서버에 명령어를 바로 반영하지 못했습니다", getattr(guild, "name", guild), exc_info=True)
        try:
            SYNC_MARKER.write_text(
                json.dumps({"signature": signature, "synced_at": _now().isoformat(timespec="seconds")}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            log.warning("명령어 등록 기록을 저장하지 못했습니다", exc_info=True)

    async def _resolve_targets(self) -> None:
        if self.log_channel is None and LOG_CHANNEL_ID:
            try:
                self.log_channel = self.get_channel(LOG_CHANNEL_ID) or await self.fetch_channel(LOG_CHANNEL_ID)
            except Exception:
                log.exception("로그 채널(%s)을 찾지 못했습니다. LOG_CHANNEL_ID 를 확인해 주세요.", LOG_CHANNEL_ID)
        if LOG_USER_ID and self.dm_user is None:
            try:
                self.dm_user = self.get_user(LOG_USER_ID) or await self.fetch_user(LOG_USER_ID)
            except Exception:
                log.exception("디엠 받을 사용자(%s)를 찾지 못했습니다.", LOG_USER_ID)

    # -- 전송 ---------------------------------------------------------------

    def enqueue(self, item: LogItem) -> None:
        self.queue.put_nowait(item)

    # -- 타이머 -------------------------------------------------------------

    def start_timer(self, channel, user, minutes: int, memo: str) -> None:
        task = asyncio.create_task(
            self._run_timer(channel, user, minutes, memo), name=f"timer-{minutes}m"
        )
        self._timers.add(task)
        task.add_done_callback(self._timers.discard)
        log.info("타이머 시작: %s분 · %s · %s", minutes, getattr(channel, "name", "?"), memo or "(메모 없음)")

    async def _run_timer(self, channel, user, minutes: int, memo: str) -> None:
        try:
            await asyncio.sleep(minutes * 60)
            await channel.send(
                content=f"{getattr(user, 'mention', '')} ⏰".strip(),
                embed=build_timer_alert_embed(minutes, memo),
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("타이머 알림 전송 실패 (%s분)", minutes, exc_info=True)

    # -- /지우개 로그 조용히 -----------------------------------------------

    def suppress_delete_logs(self, channel_id: int, seconds: float = 20.0) -> None:
        """`/지우개` 가 지운 메시지는 한 건짜리 삭제 로그를 따로 남기지 않는다."""
        self._purge_suppress[channel_id] = time.monotonic() + seconds

    def delete_log_suppressed(self, message) -> bool:
        channel_id = getattr(getattr(message, "channel", None), "id", 0)
        until = self._purge_suppress.get(channel_id, 0.0)
        if not until:
            return False
        if until <= time.monotonic():
            self._purge_suppress.pop(channel_id, None)
            return False
        return True

    async def _sender(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            item = await self.queue.get()
            try:
                await self._deliver(item)
            except Exception:
                log.exception("로그 전송 실패")
            finally:
                self.queue.task_done()

    async def _deliver(self, item: LogItem) -> None:
        if self.log_channel is None:
            await self._resolve_targets()
        if self.log_channel is not None:
            await self._send(self.log_channel, item)
        if LOG_USER_ID:
            if self.dm_user is None:
                await self._resolve_targets()
            if self.dm_user is not None:
                try:
                    await self._send(self.dm_user, item)
                except Exception:
                    log.warning("디엠 사본 전송 실패", exc_info=True)

    async def _send(self, target, item: LogItem) -> None:
        batches = [item.files[i:i + MAX_FILES_PER_MESSAGE] for i in range(0, len(item.files), MAX_FILES_PER_MESSAGE)]
        if not batches:
            batches = [[]]
        for index, batch in enumerate(batches):
            files = [discord.File(io.BytesIO(data), filename=name) for name, data in batch]
            embed = item.embed if index == 0 else None
            await target.send(embed=embed, files=files or None)

    # -- 메시지 -------------------------------------------------------------

    def _skip(self, message) -> bool:
        if getattr(message, "guild", None) is None:
            return True
        if not from_source_guild(message):
            return True
        if getattr(getattr(message, "author", None), "id", None) == getattr(self.user, "id", None):
            return True
        if getattr(getattr(message, "channel", None), "id", None) == LOG_CHANNEL_ID:
            return True
        return False

    async def on_message(self, message: discord.Message) -> None:
        if self._skip(message):
            return
        attachments = list(getattr(message, "attachments", []) or [])
        if not attachments:
            return

        saved: list[tuple[str, int]] = []
        kept: list[tuple[str, bytes]] = []
        skipped = []
        for attachment in attachments:
            if not logfmt.should_reupload(getattr(attachment, "size", None), MAX_UPLOAD_BYTES):
                skipped.append(attachment)
                continue
            try:
                data = await attachment.read()
            except Exception:
                log.warning("첨부파일 내려받기 실패: %s", getattr(attachment, "filename", "?"), exc_info=True)
                skipped.append(attachment)
                continue
            name = getattr(attachment, "filename", "file")
            kept.append((name, data))
            saved.append((name, len(data)))

        if kept:
            self.cache.put(getattr(message, "id", 0), kept)

        embed = build_attachment_embed(message, saved, skipped)
        image_name = None
        for name, _ in kept:
            if name.lower().endswith(IMAGE_EXT):
                image_name = name
                break
        if image_name:
            embed.set_image(url=f"attachment://{image_name}")
        self.enqueue(LogItem(embed, kept, image_name))

    async def on_message_delete(self, message: discord.Message) -> None:
        if self._skip(message):
            return
        if self.delete_log_suppressed(message):
            return
        cached = self.cache.get(getattr(message, "id", 0))
        self.cache.drop(getattr(message, "id", 0))
        names = [name for name, _ in cached] or [
            getattr(a, "filename", "파일") for a in (getattr(message, "attachments", []) or [])
        ]
        embed = build_delete_embed(message, names)
        self.enqueue(LogItem(embed, cached))

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if self._skip(after):
            return
        if getattr(before, "content", None) == getattr(after, "content", None):
            if len(getattr(before, "attachments", []) or []) == len(getattr(after, "attachments", []) or []):
                return
        embed = build_edit_embed(before, after)
        self.enqueue(LogItem(embed))

    # -- 멤버 ---------------------------------------------------------------

    async def on_member_join(self, member: discord.Member) -> None:
        if not from_source_guild(member):
            return
        self.enqueue(LogItem(build_member_join_embed(member)))

    async def on_member_remove(self, member: discord.Member) -> None:
        if not from_source_guild(member):
            return
        self.enqueue(LogItem(build_member_leave_embed(member)))

    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        if SOURCE_GUILD_ID and getattr(guild, "id", None) != SOURCE_GUILD_ID:
            return
        self.enqueue(LogItem(build_member_ban_embed(guild, user)))

    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if not from_source_guild(after):
            return
        changes = []
        if getattr(before, "nick", None) != getattr(after, "nick", None):
            changes.append(f"닉네임: {before.nick or before.name} → {after.nick or after.name}")
        old_roles = {r.id: r.name for r in getattr(before, "roles", [])}
        new_roles = {r.id: r.name for r in getattr(after, "roles", [])}
        added = [name for rid, name in new_roles.items() if rid not in old_roles]
        removed = [name for rid, name in old_roles.items() if rid not in new_roles]
        if added:
            changes.append("역할 추가: " + ", ".join(added))
        if removed:
            changes.append("역할 제거: " + ", ".join(removed))
        if changes:
            self.enqueue(LogItem(build_member_update_embed(before, after, changes)))

    # -- 음성 ---------------------------------------------------------------

    async def on_voice_state_update(self, member: discord.Member, before, after) -> None:
        if getattr(member, "bot", False):
            return
        if not from_source_guild(member):
            return
        described = logfmt.describe_voice(before, after)
        if described is None:
            return
        kind, text = described
        self.enqueue(LogItem(build_voice_embed(member, kind, text)))

    # -- 채널 / 역할 --------------------------------------------------------

    async def on_guild_channel_create(self, channel) -> None:
        if getattr(channel, "id", None) == LOG_CHANNEL_ID:
            return
        if not from_source_guild(channel):
            return
        self.enqueue(LogItem(build_channel_embed("생성", channel)))

    async def on_guild_channel_delete(self, channel) -> None:
        if getattr(channel, "id", None) == LOG_CHANNEL_ID:
            return
        if not from_source_guild(channel):
            return
        self.enqueue(LogItem(build_channel_embed("삭제", channel)))

    async def on_guild_channel_update(self, before, after) -> None:
        if getattr(after, "id", None) == LOG_CHANNEL_ID:
            return
        if not from_source_guild(after):
            return
        changes = logfmt.describe_changes(
            before, after, ("name", "topic", "nsfw", "slowmode_delay", "category_id", "position")
        )
        if changes:
            self.enqueue(LogItem(build_channel_embed("변경", after, changes)))

    async def on_guild_role_create(self, role) -> None:
        if not from_source_guild(role):
            return
        self.enqueue(LogItem(build_role_embed("생성", role)))

    async def on_guild_role_delete(self, role) -> None:
        if not from_source_guild(role):
            return
        self.enqueue(LogItem(build_role_embed("삭제", role)))

    async def on_guild_role_update(self, before, after) -> None:
        if not from_source_guild(after):
            return
        changes = logfmt.describe_changes(before, after, ("name", "color", "hoist", "mentionable", "position"))
        changes.extend(permission_diff(before, after))
        if changes:
            self.enqueue(LogItem(build_role_embed("변경", after, changes)))


# ---------------------------------------------------------------------------
# 24시간 무료 클라우드(Render 웹 서비스)용 초간단 상태 확인 서버
# ---------------------------------------------------------------------------

async def _start_health_server() -> None:
    try:
        from aiohttp import web
    except Exception:
        log.warning("aiohttp 가 없어 상태 확인 서버를 켜지 못했습니다.")
        return
    port = int(os.getenv("PORT", "0") or 0)
    if not port:
        return

    async def ping(_request):
        return web.Response(text="log bot is alive")

    app = web.Application()
    app.router.add_get("/", ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("상태 확인 서버 켜짐 (포트 %s)", port)


def main() -> None:
    if not TOKEN:
        raise SystemExit(
            "DISCORD_TOKEN 이 없습니다.\n"
            "실행하기.bat 을 실행하면 토큰을 물어보고 .env 파일을 만들어 줍니다.\n"
            "직접 넣으려면 .env.example 을 복사해 .env 로 이름을 바꾸고 DISCORD_TOKEN= 뒤에 붙여넣으세요."
        )
    if not LOG_CHANNEL_ID:
        raise SystemExit("LOG_CHANNEL_ID 가 없습니다. 로그를 남길 채널 ID를 .env 에 넣어 주세요.")

    bot = LogBot()
    try:
        bot.run(TOKEN, log_handler=None)
    except discord.LoginFailure:
        raise SystemExit("봇 토큰이 올바르지 않습니다. 개발자 포털에서 토큰을 다시 확인해 주세요.")


if __name__ == "__main__":
    main()
