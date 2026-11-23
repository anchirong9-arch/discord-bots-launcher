#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""백수톡 디코봇 앱 아이콘 만들기.

    python assets/make_app_icon.py

- 결과: assets/app.ico (16~256px), assets/app-icon-256.png
- 바탕화면 바로가기(create-shortcut.ps1)가 assets/app.ico 를 씁니다.
- Pillow 필요:  pip install pillow
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
MASTER = 512

C1 = (114, 137, 255)      # 밝은 블루퍼플 (왼쪽 위)
C2 = (71, 78, 200)        # 진한 블루퍼플 (오른쪽 아래)
INK = (255, 255, 255)


def gradient(size: int) -> Image.Image:
    """왼쪽 위 → 오른쪽 아래 대각선 그라데이션."""
    base = Image.new("RGB", (size, size))
    px = base.load()
    for y in range(size):
        for x in range(size):
            t = (x / (size - 1) + y / (size - 1)) / 2
            px[x, y] = (
                round(C1[0] + (C2[0] - C1[0]) * t),
                round(C1[1] + (C2[1] - C1[1]) * t),
                round(C1[2] + (C2[2] - C1[2]) * t),
            )
    return base


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size * 4 - 1, size * 4 - 1), radius=radius * 4, fill=255
    )
    return mask.resize((size, size), Image.LANCZOS)


def build() -> Image.Image:
    size = MASTER
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg = gradient(size).convert("RGBA")

    # 위쪽 하이라이트
    shade = Image.new("L", (size, size), 0)
    sd = ImageDraw.Draw(shade)
    for i in range(size):
        sd.line([(0, i), (size, i)], fill=max(0, int(44 * (1 - i / (size * 0.55)))))
    bg = Image.composite(Image.new("RGBA", (size, size), (255, 255, 255, 255)), bg, shade)

    icon.paste(bg, (0, 0), rounded_mask(size, int(size * 0.225)))
    draw = ImageDraw.Draw(icon)

    # 안테나
    draw.line([(256, 176), (256, 120)], fill=INK, width=16)
    draw.ellipse([238, 88, 274, 124], fill=INK)

    # 로봇 얼굴 (둥근 사각형)
    draw.rounded_rectangle([118, 168, 394, 392], radius=66, fill=INK)

    # 눈 두 개 — 배경색으로 뚫린 느낌
    eye = (74, 82, 205)
    draw.ellipse([188, 236, 236, 284], fill=eye)
    draw.ellipse([276, 236, 324, 284], fill=eye)

    # 입
    draw.rounded_rectangle([214, 314, 298, 334], radius=10, fill=eye)
    return icon


def main() -> int:
    icon = build()
    png = HERE / "app-icon-256.png"
    icon.resize((256, 256), Image.LANCZOS).save(png)
    ico = HERE / "app.ico"
    icon.save(ico, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("만들었습니다:", ico)
    print("만들었습니다:", png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
