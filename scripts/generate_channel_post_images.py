from __future__ import annotations

import argparse
import math
import struct
import zlib
from pathlib import Path


PALETTE = [
    ((21, 21, 21), (217, 74, 56), (246, 241, 232)),
    ((246, 241, 232), (217, 74, 56), (21, 21, 21)),
    ((26, 37, 34), (168, 183, 161), (246, 241, 232)),
    ((23, 35, 48), (159, 184, 200), (246, 241, 232)),
    ((52, 36, 30), (216, 196, 163), (246, 241, 232)),
    ((21, 21, 21), (159, 184, 200), (246, 241, 232)),
    ((246, 241, 232), (168, 183, 161), (21, 21, 21)),
]


POSTS = [
    "pinned-post",
    "long-task",
    "memory",
    "payments",
    "product-update",
    "prompt-day",
    "week-summary",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate branded PNG cards for Telegram channel posts.")
    parser.add_argument("--output-dir", default="assets/channel-posts")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    return parser.parse_args()


def blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(a[i] * (1 - t) + b[i] * t))) for i in range(3))


def set_px(pixels: bytearray, width: int, height: int, x: int, y: int, color: tuple[int, int, int]) -> None:
    if x < 0 or y < 0 or x >= width or y >= height:
        return
    idx = (y * width + x) * 3
    pixels[idx : idx + 3] = bytes(color)


def draw_disc(
    pixels: bytearray,
    width: int,
    height: int,
    cx: int,
    cy: int,
    radius: int,
    color: tuple[int, int, int],
    alpha: float = 1.0,
) -> None:
    r2 = radius * radius
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            dx = x - cx
            dy = y - cy
            if dx * dx + dy * dy > r2:
                continue
            if x < 0 or y < 0 or x >= width or y >= height:
                continue
            idx = (y * width + x) * 3
            current = tuple(pixels[idx + i] for i in range(3))
            pixels[idx : idx + 3] = bytes(blend(current, color, alpha))


def draw_line(
    pixels: bytearray,
    width: int,
    height: int,
    points: list[tuple[int, int]],
    color: tuple[int, int, int],
    radius: int,
) -> None:
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        steps = max(abs(x2 - x1), abs(y2 - y1), 1)
        for step in range(steps + 1):
            t = step / steps
            x = round(x1 * (1 - t) + x2 * t)
            y = round(y1 * (1 - t) + y2 * t)
            draw_disc(pixels, width, height, x, y, radius, color, 0.86)


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        start = y * stride
        raw.extend(pixels[start : start + stride])
    payload = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
            png_chunk(b"IEND", b""),
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def generate_card(path: Path, width: int, height: int, variant: int) -> None:
    bg, accent, light = PALETTE[variant % len(PALETTE)]
    pixels = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            t = (x / width) * 0.55 + (y / height) * 0.45
            wave = (math.sin((x + variant * 97) / 82) + math.cos((y + variant * 53) / 61)) * 0.06
            color = blend(bg, light, max(0.0, min(1.0, 0.08 + t * 0.22 + wave)))
            set_px(pixels, width, height, x, y, color)

    draw_disc(pixels, width, height, width - 190, 140, 190, accent, 0.16)
    draw_disc(pixels, width, height, 180, height - 120, 230, light, 0.08)

    points = []
    for i in range(0, width + 80, 18):
        x = i - 40
        y = int(height * 0.50 + math.sin((i / 84) + variant) * 92 + math.sin(i / 37) * 24)
        points.append((x, y))
    draw_line(pixels, width, height, points, accent, 5)

    knot_x = int(width * (0.55 + 0.08 * math.sin(variant)))
    knot_y = int(height * 0.50)
    for radius in (112, 82, 52):
        loop = []
        for step in range(0, 361, 6):
            angle = math.radians(step)
            loop.append(
                (
                    int(knot_x + math.cos(angle) * radius * 1.18),
                    int(knot_y + math.sin(angle) * radius * 0.58),
                )
            )
        draw_line(pixels, width, height, loop, accent, 3)

    for i in range(5):
        draw_disc(
            pixels,
            width,
            height,
            int(width * (0.16 + i * 0.12)),
            int(height * (0.22 + 0.04 * math.sin(i + variant))),
            10 + i % 3,
            light,
            0.62,
        )

    write_png(path, width, height, pixels)


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    for index, name in enumerate(POSTS):
        path = output_dir / f"{name}.png"
        generate_card(path, args.width, args.height, index)
        print(f"Generated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
