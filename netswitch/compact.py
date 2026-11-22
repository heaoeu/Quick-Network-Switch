"""简洁面板：固定两张网卡卡片（大号百分比 + 进度条 + 数据来源）。"""
from __future__ import annotations

import tkinter as tk

from .netinfo import Adapter
from .ui_common import (
    ACCENT,
    BG,
    BORDER,
    FAINT,
    MUTED,
    RED,
    SURFACE,
    SURFACE_2,
    TEXT,
    YELLOW,
    FlatButton,
    ProgressBar,
    center_window,
    label,
)


def _quality(adapter: Adapter) -> tuple[int | None, str, str]:
    if not adapter.is_up:
        return 0, FAINT, "未连接"
    if adapter.signal is not None:
        value = adapter.signal.quality
        if value >= 75:
            color = ACCENT
        elif value >= 40:
            color = YELLOW
        else:
            color = RED
        return value, color, "信号质量"
    return 100, ACCENT, "链路可用"


def _source_text(adapter: Adapter) -> str:
    if not adapter.is_up:
        return "IP Helper API · 未连接"
    if adapter.signal is not None:
        ssid = adapter.signal.ssid or "Wi-Fi"
        return f"WLAN API · {ssid}"
    if adapter.is_wifi:
        return "IP Helper API · 链路可用（WLAN API 不可用）"
    return "IP Helper API · 链路可用"


class AdapterCard(tk.Frame):
    def __init__(self, master, bg: str = SURFACE):
        super().__init__(master, bg=bg, highlightthickness=1, highlightbackground=BORDER)
        self._bg = bg
        self.grid_columnconfigure(0, weight=1)
        self.title = label(self, "等待检测网卡", fg=TEXT, size=11, weight="bold", anchor="w")
        self.title.grid(row=0, column=0, sticky="ew", padx=18, pady=(15, 0))
        self.subtitle = label(self, "", fg=MUTED, size=9, anchor="w")
        self.subtitle.grid(row=1, column=0, sticky="ew", padx=18, pady=(2, 0))

        percent_row = tk.Frame(self, bg=bg)
        percent_row.grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 0))
        self.percent = label(percent_row, "--", fg=TEXT, size=34, weight="bold", anchor="w")
        self.percent.pack(side="left")
        self.percent_suffix = label(percent_row, "", fg=MUTED, size=10, anchor="sw")
        self.percent_suffix.pack(side="left", padx=(2, 0), pady=(0, 5))
        self.quality = label(percent_row, "未连接", fg=FAINT, size=9, anchor="e")
        self.quality.pack(side="right", pady=(0, 5))

        self.bar = ProgressBar(self, bg=bg, height=11)
        self.bar.grid(row=3, column=0, sticky="ew", padx=18, pady=(4, 0))
        self.detail = label(self, "", fg=MUTED, size=9, anchor="w")
        self.detail.grid(row=4, column=0, sticky="ew", padx=18, pady=(10, 0))
        self.profile = label(self, "", fg=TEXT, size=9, anchor="w")
        self.profile.grid(row=5, column=0, sticky="ew", padx=18, pady=(2, 0))
        self.source = label(self, "", fg=FAINT, size=8, anchor="w")
        self.source.grid(row=6, column=0, sticky="ew", padx=18, pady=(4, 14))
        self.grid_rowconfigure(6, weight=1)

    def set_adapter(self, adapter: Adapter | None, profile_name: str = "") -> None:
        if adapter is None:
            self.title.configure(text="第二块网卡")
            self.subtitle.configure(text="未检测到可配置的物理网卡")
            self.percent.configure(text="--", fg=FAINT)
            self.percent_suffix.configure(text="")
            self.quality.configure(text="等待设备", fg=FAINT)
            self.bar.set_value(None, FAINT)
            self.detail.configure(text="无需操作；只显示已连接或可用的网卡")
            self.profile.configure(text="")
            self.source.configure(text="数据来源：IP Helper API")
            return
        self.title.configure(text=adapter.name or adapter.description, fg=TEXT)
        self.subtitle.configure(text=adapter.description if adapter.description != adapter.name else adapter.type_label)
        value, color, quality_text = _quality(adapter)
        self.percent.configure(text="--" if value is None else str(value), fg=color)
        self.percent_suffix.configure(text="" if value is None else "%")
        self.quality.configure(text=quality_text, fg=color)
        self.bar.set_value(value, color)
        if adapter.is_up:
            detail = adapter.ipv4 or "等待 IPv4 地址"
            if adapter.mask:
                detail += f" / {adapter.mask}"
        else:
            detail = "网卡未连接"
        self.detail.configure(text=detail)
        if profile_name:
            self.profile.configure(text=f"当前方案：{profile_name}", fg=ACCENT)
        elif adapter.dhcp:
            self.profile.configure(text="当前：自动获取（DHCP）", fg=MUTED)
        elif adapter.is_up:
            self.profile.configure(text="当前：静态 IP（未匹配方案）", fg=MUTED)
        else:
            self.profile.configure(text="")
        self.source.configure(text="数据来源：" + _source_text(adapter))


class CompactWindow:
    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title("网络快捷切换")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.hide)
        self.win.bind("<Escape>", lambda _e: self.hide())
        self._snapshot = None
        self._build()
        center_window(self.win, 820, 430)

    def _build(self) -> None:
        header = tk.Frame(self.win, bg=BG)
        header.pack(fill="x", padx=20, pady=(16, 8))
        title_box = tk.Frame(header, bg=BG)
        title_box.pack(side="left", fill="x", expand=True)
        label(title_box, "网络快捷切换", fg=TEXT, size=16, weight="bold").pack(anchor="w")
        self.subtitle = label(title_box, "正在读取网卡…", fg=MUTED, size=9)
        self.subtitle.pack(anchor="w", pady=(3, 0))
        FlatButton(header, "方案管理", self.app.show_manager, bg=SURFACE_2, fg=TEXT, hover=BORDER, padx=14).pack(
            side="right", padx=(8, 0)
        )
        FlatButton(header, "刷新", self.app.request_refresh, bg=SURFACE_2, fg=TEXT, hover=BORDER, padx=14).pack(
            side="right", padx=(8, 0)
        )

        footer = tk.Frame(self.win, bg=BG)
        footer.pack(side="bottom", fill="x", padx=22, pady=(6, 14))
        self.status = label(footer, "准备就绪", fg=FAINT, size=8, anchor="w")
        self.status.pack(side="left")
        self.updated = label(footer, "", fg=FAINT, size=8, anchor="e")
        self.updated.pack(side="right")

        cards = tk.Frame(self.win, bg=BG)
        cards.pack(fill="both", expand=True, padx=20, pady=(4, 2))
        cards.grid_columnconfigure(0, weight=1)
        cards.grid_columnconfigure(1, weight=1)
        self.card1 = AdapterCard(cards)
        self.card1.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.card2 = AdapterCard(cards)
        self.card2.grid(row=0, column=1, sticky="nsew", padx=(8, 0))


    def show(self) -> None:
        try:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
        except Exception:
            pass

    def hide(self) -> None:
        try:
            self.win.withdraw()
        except Exception:
            pass

    def is_visible(self) -> bool:
        try:
            return self.win.winfo_viewable()
        except Exception:
            return False

    def set_busy(self, text: str, busy: bool = True) -> None:
        self.status.configure(text=text, fg=YELLOW if busy else FAINT)

    def set_status(self, text: str, error: bool = False) -> None:
        self.status.configure(text=text, fg=RED if error else MUTED)

    def refresh(self, snapshot) -> None:
        self._snapshot = snapshot
        adapter = snapshot.selected
        candidates = [a for a in snapshot.adapters if a.is_configurable and a.if_index != (adapter.if_index if adapter else -1)]
        second = candidates[0] if candidates else None
        active_name = ""
        if snapshot.active_profile_id:
            for profile in self.app.settings.profiles:
                if profile.id == snapshot.active_profile_id:
                    active_name = profile.name
                    break
        self.card1.set_adapter(adapter, active_name)
        self.card2.set_adapter(second)
        if adapter is None:
            self.subtitle.configure(text="未选择网卡，请打开方案管理")
        else:
            if active_name:
                prefix = f"当前方案：{active_name}"
            elif adapter.dhcp:
                prefix = "当前：自动获取（DHCP）"
            elif adapter.is_up:
                prefix = "当前：静态 IP（未匹配方案）"
            else:
                prefix = "当前网卡未连接"
            self.subtitle.configure(text=f"{adapter.type_label} · {prefix}")
        self.updated.configure(text=f"刷新 {snapshot.timestamp_text}")
        if not self.status.cget("text") or self.status.cget("text") in ("正在读取网卡…", "准备就绪"):
            self.status.configure(text="托盘右键菜单可快速切换；点「刷新」更新状态", fg=FAINT)
