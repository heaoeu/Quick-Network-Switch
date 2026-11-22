"""Tk 界面公共主题、按钮、进度条与小型布局工具。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .win32 import center_window

BG = "#0F141B"
SURFACE = "#171F2A"
SURFACE_2 = "#202B39"
SURFACE_3 = "#273446"
BORDER = "#2C3A4D"
TEXT = "#E8EEF7"
MUTED = "#8FA1B8"
FAINT = "#64748B"
ACCENT = "#34D399"
ACCENT_DARK = "#0E7C5A"
BLUE = "#3B82F6"
BLUE_DARK = "#1D4ED8"
YELLOW = "#F4B942"
RED = "#F87171"
RED_DARK = "#B91C1C"
WHITE = "#FFFFFF"

FONT_FAMILY = "Microsoft YaHei UI"
FONT_MONO = "Consolas"


def apply_theme(root: tk.Misc) -> None:
    root.configure(bg=BG)
    try:
        root.option_add("*Font", (FONT_FAMILY, 10))
        root.option_add("*selectBackground", SURFACE_3)
        root.option_add("*selectForeground", TEXT)
    except Exception:
        pass
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "Dark.TCombobox",
        fieldbackground=SURFACE_2,
        background=SURFACE_2,
        foreground=TEXT,
        arrowcolor=TEXT,
        bordercolor=BORDER,
        lightcolor=SURFACE_2,
        darkcolor=SURFACE_2,
        selectbackground=SURFACE_2,
        selectforeground=TEXT,
        padding=(8, 5),
    )
    style.map(
        "Dark.TCombobox",
        fieldbackground=[("readonly", SURFACE_2), ("disabled", SURFACE)],
        foreground=[("readonly", TEXT), ("disabled", FAINT)],
        selectbackground=[("readonly", SURFACE_2)],
        selectforeground=[("readonly", TEXT)],
        arrowcolor=[("disabled", FAINT), ("!disabled", TEXT)],
        bordercolor=[("focus", ACCENT), ("!focus", BORDER)],
    )
    style.configure(
        "Dark.Vertical.TScrollbar",
        background=SURFACE_3,
        troughcolor=SURFACE,
        bordercolor=SURFACE,
        arrowcolor=MUTED,
        lightcolor=SURFACE_3,
        darkcolor=SURFACE_3,
        gripcount=0,
        width=10,
    )
    style.map("Dark.Vertical.TScrollbar", background=[("active", BORDER)])


def make_font(size: int, weight: str = "normal", family: str | None = None) -> tuple:
    return (family or FONT_FAMILY, size, weight)


class FlatButton(tk.Button):
    """带 hover 的扁平按钮；在深色窗口里比 ttk.Button 更可控。"""

    def __init__(
        self,
        master,
        text: str,
        command=None,
        *,
        bg: str = SURFACE_2,
        fg: str = TEXT,
        hover: str = SURFACE_3,
        active_bg: str | None = None,
        font=None,
        padx: int = 14,
        pady: int = 6,
        **kwargs,
    ):
        self._bg = bg
        self._fg = fg
        self._hover = hover
        self._active_bg = active_bg or hover
        super().__init__(
            master,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg or hover,
            activeforeground=fg,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=padx,
            pady=pady,
            cursor="hand2",
            font=font or make_font(10),
            **kwargs,
        )
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self.bind("<ButtonPress-1>", self._on_press, add="+")
        self.bind("<ButtonRelease-1>", self._on_release, add="+")

    def _on_enter(self, _event=None):
        if str(self["state"]) == "normal":
            self.configure(bg=self._hover)

    def _on_leave(self, _event=None):
        if str(self["state"]) == "normal":
            self.configure(bg=self._bg)

    def _on_press(self, _event=None):
        if str(self["state"]) == "normal":
            self.configure(bg=self._active_bg)

    def _on_release(self, event=None):
        if str(self["state"]) != "normal":
            return
        try:
            inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        except Exception:
            inside = True
        self.configure(bg=self._hover if inside else self._bg)

    def set_colors(self, bg: str, fg: str, hover: str) -> None:
        self._bg, self._fg, self._hover = bg, fg, hover
        self.configure(bg=bg, fg=fg, activebackground=hover, activeforeground=fg)


class LinkButton(tk.Label):
    def __init__(self, master, text: str, command=None, *, fg: str = ACCENT, font=None, **kwargs):
        super().__init__(
            master,
            text=text,
            fg=fg,
            bg=kwargs.pop("bg", master.cget("bg")),
            cursor="hand2",
            font=font or make_font(9),
            **kwargs,
        )
        self._fg = fg
        self._command = command
        self.bind("<Button-1>", lambda _e: self._command() if self._command else None)
        self.bind("<Enter>", lambda _e: self.configure(fg=WHITE))
        self.bind("<Leave>", lambda _e: self.configure(fg=self._fg))


class ProgressBar(tk.Canvas):
    def __init__(self, master, *, bg: str, width: int = 300, height: int = 12, **kwargs):
        super().__init__(
            master,
            width=width,
            height=height,
            bg=bg,
            highlightthickness=0,
            bd=0,
            **kwargs,
        )
        self._bg = bg
        self._value = 0.0
        self._color = ACCENT
        self._track = self.create_line(5, height // 2, width - 5, height // 2, width=height, fill=BORDER, capstyle="round")
        self._fill = self.create_line(5, height // 2, 5, height // 2, width=height, fill=self._color, capstyle="round")
        self.bind("<Configure>", self._redraw)

    def set_value(self, value: float | None, color: str = ACCENT) -> None:
        self._value = 0.0 if value is None else max(0.0, min(100.0, float(value)))
        self._color = color
        self._redraw()

    def _redraw(self, _event=None):
        width = max(10, self.winfo_width())
        height = max(4, self.winfo_height())
        y = height // 2
        self.coords(self._track, 5, y, width - 5, y)
        self.itemconfigure(self._track, width=height)
        span = max(0, width - 10)
        end = 5 + span * (self._value / 100.0)
        self.coords(self._fill, 5, y, max(5, end), y)
        self.itemconfigure(self._fill, width=height, fill=self._color, state="normal" if self._value > 0 else "hidden")


class VDivider(tk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, width=1, bg=BORDER, **kwargs)


def clear_children(widget) -> None:
    for child in widget.winfo_children():
        child.destroy()


def label(parent, text: str, *, fg: str = TEXT, bg: str | None = None, size: int = 10,
          weight: str = "normal", family: str | None = None, **kwargs) -> tk.Label:
    return tk.Label(
        parent,
        text=text,
        fg=fg,
        bg=bg or parent.cget("bg"),
        font=make_font(size, weight, family),
        **kwargs,
    )


def entry(parent, textvariable=None, *, width: int = 20) -> tk.Entry:
    return tk.Entry(
        parent,
        textvariable=textvariable,
        width=width,
        bg=SURFACE_2,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=ACCENT,
        font=make_font(10),
    )


def set_text(widget: tk.Text, text: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", text)
    widget.configure(state="disabled")
