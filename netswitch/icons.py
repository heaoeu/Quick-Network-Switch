"""用 GDI 直接绘制托盘图标，不依赖 Pillow，也不落地任何图片文件。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from .win32 import gdi32, get_dpi_for_system, user32


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HANDLE),
        ("hbmColor", wintypes.HANDLE),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.CreateIconIndirect.restype = wintypes.HICON
user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
user32.DestroyIcon.restype = wintypes.BOOL
user32.DestroyIcon.argtypes = [wintypes.HICON]

gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateBitmap.restype = wintypes.HBITMAP
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
gdi32.CreatePen.restype = wintypes.HPEN
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetStockObject.restype = wintypes.HGDIOBJ
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.PatBlt.restype = wintypes.BOOL
gdi32.PatBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.RoundRect.restype = wintypes.BOOL
gdi32.RoundRect.argtypes = [
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
]
gdi32.Ellipse.restype = wintypes.BOOL
gdi32.Ellipse.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.MoveToEx.restype = wintypes.BOOL
gdi32.MoveToEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
gdi32.LineTo.restype = wintypes.BOOL
gdi32.LineTo.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]

SM_CXSMICON = 49
NULL_PEN = 0x00A8
BLACKNESS = 0x00000042


def _colorref(rgb_hex: str) -> int:
    text = rgb_hex.lstrip("#")
    r, g, b = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    return (b << 16) | (g << 8) | r


def icon_size() -> int:
    metric = user32.GetSystemMetrics(SM_CXSMICON) or 16
    dpi = get_dpi_for_system()
    return max(32, int(round(metric * 2 * dpi / 96)))


def _rounded_mask(size: int) -> tuple[ctypes.Array, int]:
    stride = ((size + 15) // 16) * 2
    bits = ctypes.create_string_buffer(stride * size)
    radius = max(2.0, size * 0.22)
    raw = bytearray(bits.raw)
    for y in range(size):
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            inside = True
            if px < radius and py < radius:
                inside = (px - radius) ** 2 + (py - radius) ** 2 <= radius**2
            elif px > size - radius and py < radius:
                inside = (px - (size - radius)) ** 2 + (py - radius) ** 2 <= radius**2
            elif px < radius and py > size - radius:
                inside = (px - radius) ** 2 + (py - (size - radius)) ** 2 <= radius**2
            elif px > size - radius and py > size - radius:
                inside = (
                    (px - (size - radius)) ** 2 + (py - (size - radius)) ** 2
                    <= radius**2
                )
            if not inside:
                raw[y * stride + x // 8] |= 0x80 >> (x % 8)
    bits.raw = bytes(raw)
    return bits, stride


def create_tray_icon() -> int:
    size = icon_size()
    screen = user32.GetDC(None)
    if not screen:
        return 0
    mem = gdi32.CreateCompatibleDC(screen)
    if not mem:
        user32.ReleaseDC(None, screen)
        return 0
    color_bmp = gdi32.CreateCompatibleBitmap(screen, size, size)
    mask_bits, _ = _rounded_mask(size)
    mask_bmp = gdi32.CreateBitmap(size, size, 1, 1, mask_bits)
    hicon = 0
    old_bmp = None
    bg_brush = white_brush = dot_brush = None
    line_pen = None
    old_pen = None
    old_brush = None
    try:
        old_bmp = gdi32.SelectObject(mem, color_bmp)
        gdi32.PatBlt(mem, 0, 0, size, size, BLACKNESS)

        bg_brush = gdi32.CreateSolidBrush(_colorref("#2563EB"))
        null_pen = gdi32.GetStockObject(NULL_PEN)
        old_pen = gdi32.SelectObject(mem, null_pen)
        old_brush = gdi32.SelectObject(mem, bg_brush)
        radius = int(size * 0.22)
        gdi32.RoundRect(mem, 0, 0, size, size, radius * 2, radius * 2)
        gdi32.SelectObject(mem, old_brush)
        old_brush = None
        gdi32.DeleteObject(bg_brush)
        bg_brush = None

        line_pen = gdi32.CreatePen(0, max(1, int(round(size * 0.075))), _colorref("#FFFFFF"))
        gdi32.SelectObject(mem, line_pen)
        left = (int(size * 0.27), int(size * 0.64))
        top = (int(size * 0.71), int(size * 0.30))
        bottom = (int(size * 0.71), int(size * 0.69))
        gdi32.MoveToEx(mem, left[0], left[1], None)
        gdi32.LineTo(mem, top[0], top[1])
        gdi32.MoveToEx(mem, left[0], left[1], None)
        gdi32.LineTo(mem, bottom[0], bottom[1])

        white_brush = gdi32.CreateSolidBrush(_colorref("#FFFFFF"))
        old_brush = gdi32.SelectObject(mem, white_brush)
        node = max(2, int(round(size * 0.095)))
        for cx, cy in (left, top, bottom):
            gdi32.Ellipse(mem, cx - node, cy - node, cx + node, cy + node)
        gdi32.SelectObject(mem, old_brush)
        old_brush = None
        gdi32.DeleteObject(white_brush)
        white_brush = None

        dot_brush = gdi32.CreateSolidBrush(_colorref("#34D399"))
        old_brush = gdi32.SelectObject(mem, dot_brush)
        dot = max(2, int(round(size * 0.075)))
        cx, cy = int(size * 0.79), int(size * 0.79)
        gdi32.Ellipse(mem, cx - dot, cy - dot, cx + dot, cy + dot)
        gdi32.SelectObject(mem, old_brush)
        old_brush = None
        gdi32.DeleteObject(dot_brush)
        dot_brush = None

        info = ICONINFO()
        info.fIcon = True
        info.hbmMask = mask_bmp
        info.hbmColor = color_bmp
        hicon = int(user32.CreateIconIndirect(ctypes.byref(info)) or 0)
    finally:
        for brush in (bg_brush, white_brush, dot_brush):
            if brush:
                try:
                    gdi32.DeleteObject(brush)
                except Exception:
                    pass
        if old_brush:
            try:
                gdi32.SelectObject(mem, old_brush)
            except Exception:
                pass
        if line_pen:
            try:
                gdi32.DeleteObject(line_pen)
            except Exception:
                pass
        if old_pen:
            try:
                gdi32.SelectObject(mem, old_pen)
            except Exception:
                pass
        if old_bmp:
            try:
                gdi32.SelectObject(mem, old_bmp)
            except Exception:
                pass
        if mask_bmp:
            gdi32.DeleteObject(mask_bmp)
        if color_bmp:
            gdi32.DeleteObject(color_bmp)
        if mem:
            gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, screen)
    return hicon


def destroy_icon(hicon: int | None) -> None:
    if hicon:
        try:
            user32.DestroyIcon(hicon)
        except Exception:
            pass
