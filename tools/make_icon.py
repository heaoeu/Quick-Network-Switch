#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成网络快捷切换的 app.ico / app-256.png。

只用 Python 标准库：自己画 RGBA、做超采样、写 PNG/ICO，不依赖 Pillow。
图标语义：蓝色圆角底 + 两条反向箭头（快速切换）+ 绿色状态点。
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SS = 4  # 每个尺寸按 4 倍分辨率绘制，再缩小，得到平滑边缘

TOP = (79, 141, 247)
BOTTOM = (29, 78, 216)
WHITE = (255, 255, 255)
GREEN = (52, 211, 153)

RADIUS = 0.225
ARROW_THICK = 0.078
UPPER_Y = 0.355
LOWER_Y = 0.645
UPPER_TIP = 0.820
LOWER_TIP = 0.180
ARROW_BASE = 0.665
ARROW_HALF = 0.088
DOT_X = 0.800
DOT_Y = 0.180
DOT_R = 0.060


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def _mix(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def _sd_round_rect(px: float, py: float, hw: float, hh: float, radius: float) -> float:
    qx = abs(px) - (hw - radius)
    qy = abs(py) - (hh - radius)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    inside = min(max(qx, qy), 0.0)
    return outside + inside - radius


def _sd_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    pax, pay = px - ax, py - ay
    bax, bay = bx - ax, by - ay
    denom = bax * bax + bay * bay
    h = 0.0 if denom == 0 else _clamp((pax * bax + pay * bay) / denom, 0.0, 1.0)
    return math.hypot(pax - bax * h, pay - bay * h)


def _in_triangle(px: float, py: float, a, b, c) -> bool:
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1 = sign((px, py), a, b)
    d2 = sign((px, py), b, c)
    d3 = sign((px, py), c, a)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def _put(buf: bytearray, index: int, rgb: tuple[int, int, int], alpha: int = 255) -> None:
    buf[index] = rgb[0]
    buf[index + 1] = rgb[1]
    buf[index + 2] = rgb[2]
    buf[index + 3] = alpha


def _render(size: int) -> bytearray:
    n = size * SS
    buf = bytearray(n * n * 4)
    inv = 1.0 / n

    for y in range(n):
        v = (y + 0.5) * inv
        row = y * n * 4
        for x in range(n):
            u = (x + 0.5) * inv
            if _sd_round_rect(u - 0.5, v - 0.5, 0.5, 0.5, RADIUS) > 0:
                continue
            t = _clamp(u * 0.62 + v * 0.38, 0.0, 1.0)
            r = _mix(TOP[0], BOTTOM[0], t)
            g = _mix(TOP[1], BOTTOM[1], t)
            b = _mix(TOP[2], BOTTOM[2], t)
            # 左上柔光，避免整块纯色发平。
            glow = _clamp(1.0 - ((u - 0.30) ** 2 + (v - 0.18) ** 2) / 0.11, 0.0, 1.0)
            if glow > 0:
                r = _mix(r, 255, glow * 0.14)
                g = _mix(g, 255, glow * 0.14)
                b = _mix(b, 255, glow * 0.14)
            _put(buf, row + x * 4, (r, g, b))

    # 箭头只画在包围盒里，减少无意义的形状测试。
    left = int(0.10 * n)
    right = int(0.90 * n) + 1
    top = int(0.22 * n)
    bottom = int(0.78 * n) + 1
    upper_a = (0.235, UPPER_Y)
    upper_b = (0.665, UPPER_Y)
    upper_tip = (UPPER_TIP, UPPER_Y)
    upper_t1 = (0.650, UPPER_Y - ARROW_HALF)
    upper_t2 = (0.650, UPPER_Y + ARROW_HALF)
    lower_a = (0.765, LOWER_Y)
    lower_b = (0.335, LOWER_Y)
    lower_tip = (LOWER_TIP, LOWER_Y)
    lower_t1 = (0.350, LOWER_Y - ARROW_HALF)
    lower_t2 = (0.350, LOWER_Y + ARROW_HALF)

    for y in range(top, bottom):
        v = (y + 0.5) * inv
        row = y * n * 4
        for x in range(left, right):
            u = (x + 0.5) * inv
            in_upper = (
                _sd_segment(u, v, *upper_a, *upper_b) <= ARROW_THICK / 2
                or _in_triangle(u, v, upper_tip, upper_t1, upper_t2)
            )
            in_lower = (
                _sd_segment(u, v, *lower_a, *lower_b) <= ARROW_THICK / 2
                or _in_triangle(u, v, lower_tip, lower_t1, lower_t2)
            )
            if in_upper or in_lower:
                _put(buf, row + x * 4, WHITE)

    cx, cy = DOT_X * n, DOT_Y * n
    radius = DOT_R * n
    left = max(0, int(cx - radius) - 1)
    right = min(n, int(cx + radius) + 2)
    top = max(0, int(cy - radius) - 1)
    bottom = min(n, int(cy + radius) + 2)
    for y in range(top, bottom):
        v = (y + 0.5) * inv
        row = y * n * 4
        for x in range(left, right):
            u = (x + 0.5) * inv
            if math.hypot(u - DOT_X, v - DOT_Y) <= DOT_R:
                _put(buf, row + x * 4, GREEN)
    return buf


def _downsample(buf: bytearray, src: int, factor: int) -> bytes:
    dst = src // factor
    out = bytearray(dst * dst * 4)
    area = factor * factor
    for y in range(dst):
        for x in range(dst):
            sa = sr = sg = sb = 0
            for yy in range(factor):
                base = ((y * factor + yy) * src + x * factor) * 4
                for xx in range(factor):
                    i = base + xx * 4
                    a = buf[i + 3]
                    sa += a
                    sr += buf[i] * a
                    sg += buf[i + 1] * a
                    sb += buf[i + 2] * a
            o = (y * dst + x) * 4
            if sa:
                out[o] = int(round(sr / sa))
                out[o + 1] = int(round(sg / sa))
                out[o + 2] = int(round(sb / sa))
                out[o + 3] = int(round(sa / area))
    return bytes(out)


def _png(rgba: bytes, size: int) -> bytes:
    raw = b"".join(
        b"\x00" + rgba[y * size * 4 : (y + 1) * size * 4] for y in range(size)
    )

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _bmp(rgba: bytes, size: int) -> bytes:
    pixels = bytearray(size * size * 4)
    for y in range(size):
        src_row = (size - 1 - y) * size * 4
        dst_row = y * size * 4
        for x in range(size):
            i = src_row + x * 4
            o = dst_row + x * 4
            pixels[o] = rgba[i + 2]
            pixels[o + 1] = rgba[i + 1]
            pixels[o + 2] = rgba[i]
            pixels[o + 3] = rgba[i + 3]
    mask_stride = ((size + 31) // 32) * 4
    mask = b"\x00" * (mask_stride * size)
    header = struct.pack(
        "<IiiHHIIiiII",
        40,
        size,
        size * 2,
        1,
        32,
        0,
        len(pixels) + len(mask),
        0,
        0,
        0,
        0,
    )
    return header + bytes(pixels) + mask


def build() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    images: dict[int, bytes] = {}
    for size in ICON_SIZES:
        images[size] = _downsample(_render(size), size * SS, SS)

    preview = images[256]
    (ASSETS / "app-256.png").write_bytes(_png(preview, 256))

    entries: list[tuple[int, bytes]] = []
    for size in ICON_SIZES:
        if size == 256:
            payload = _png(images[size], size)
        else:
            payload = _bmp(images[size], size)
        entries.append((size, payload))

    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    directory = bytearray()
    body = bytearray()
    for size, payload in entries:
        directory += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0,
            0,
            1,
            32,
            len(payload),
            offset,
        )
        body += payload
        offset += len(payload)
    (ASSETS / "app.ico").write_bytes(header + bytes(directory) + bytes(body))
    print(f"wrote {ASSETS / 'app.ico'}")
    print(f"wrote {ASSETS / 'app-256.png'}")


if __name__ == "__main__":
    build()
