"""主界面：网卡选择 + 方案列表（每行带编辑/删除按钮）。"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .config import Profile
from .netinfo import Adapter
from .ui_common import (
    ACCENT,
    ACCENT_DARK,
    BG,
    BORDER,
    FAINT,
    MUTED,
    RED,
    SURFACE,
    SURFACE_2,
    SURFACE_3,
    TEXT,
    YELLOW,
    FlatButton,
    center_window,
    label,
    make_font,
)

COLUMN_TITLES = ("使用", "名称", "IP 地址", "子网掩码", "默认网关", "DNS1", "DNS2", "操作")


class ProfileRow(tk.Frame):
    def __init__(self, master, manager, profile: Profile, active: bool):
        self.manager = manager
        self.profile = profile
        self.active = active
        self._hover = False
        base = SURFACE_2 if active else SURFACE
        super().__init__(
            master,
            bg=base,
            highlightthickness=1,
            highlightbackground=ACCENT if active else BORDER,
        )
        self.grid_columnconfigure(0, minsize=42)
        self.grid_columnconfigure(1, weight=1, minsize=118)
        self.grid_columnconfigure(2, minsize=118)
        self.grid_columnconfigure(3, minsize=126)
        self.grid_columnconfigure(4, minsize=118)
        self.grid_columnconfigure(5, minsize=112)
        self.grid_columnconfigure(6, minsize=112)
        self.grid_columnconfigure(7, minsize=112)
        self._labels: list[tk.Label] = []
        self.check = label(
            self,
            "✓" if active else "○",
            fg=ACCENT if active else FAINT,
            size=13,
            weight="bold",
            bg=base,
        )
        self.check.grid(row=0, column=0, padx=(10, 0), pady=9, sticky="w")
        self._labels.append(self.check)
        values = [
            profile.name,
            profile.ip,
            profile.mask,
            profile.gateway,
            profile.dns1,
            profile.dns2 or "—",
        ]
        for column, text in enumerate(values, start=1):
            widget = label(
                self,
                text,
                fg=TEXT if column == 1 else MUTED,
                size=9,
                weight="bold" if column == 1 else "normal",
                bg=base,
                anchor="w",
            )
            widget.grid(row=0, column=column, padx=(6, 6), pady=9, sticky="ew")
            self._labels.append(widget)
            widget.bind("<Button-1>", lambda _e, pid=profile.id: self.manager.app.apply_profile(pid, "ui"))
            widget.bind("<Enter>", self._enter, add="+")
            widget.bind("<Leave>", self._leave, add="+")

        actions = tk.Frame(self, bg=base)
        actions.grid(row=0, column=7, padx=(2, 8), pady=5, sticky="e")
        edit = FlatButton(
            actions,
            "编辑",
            lambda pid=profile.id: self.manager.app.open_profile_dialog(pid),
            bg=base,
            fg=MUTED,
            hover=SURFACE_3,
            font=make_font(9),
            padx=8,
            pady=3,
        )
        edit.pack(side="left", padx=(0, 2))
        delete = FlatButton(
            actions,
            "删除",
            lambda pid=profile.id: self.manager.delete_profile(pid),
            bg=base,
            fg=RED,
            hover="#3A2429",
            font=make_font(9),
            padx=8,
            pady=3,
        )
        delete.pack(side="left")
        for widget in (self.check, actions):
            widget.bind("<Enter>", self._enter, add="+")
            widget.bind("<Leave>", self._leave, add="+")
        self.check.bind("<Button-1>", lambda _e, pid=profile.id: self.manager.app.apply_profile(pid, "ui"))
        self.bind("<Enter>", self._enter, add="+")
        self.bind("<Leave>", self._leave, add="+")
        self.bind("<Button-1>", lambda _e, pid=profile.id: self.manager.app.apply_profile(pid, "ui"))
        try:
            self.bind("<MouseWheel>", self.manager._on_mousewheel, add="+")
            for widget in self._labels:
                widget.bind("<MouseWheel>", self.manager._on_mousewheel, add="+")
        except Exception:
            pass

    def _enter(self, _event=None):
        self._hover = True
        self._paint(SURFACE_3)

    def _leave(self, event=None):
        # 子控件之间移动也会触发 Leave；用坐标判断是否真的离开整行。
        try:
            x, y = self.winfo_pointerxy()
            widget = self.winfo_containing(x, y)
            while widget is not None:
                if widget is self:
                    return
                widget = getattr(widget, "master", None)
        except Exception:
            pass
        self._hover = False
        self._paint(SURFACE_2 if self.active else SURFACE)

    def _paint(self, color: str):
        base = SURFACE_2 if self.active else SURFACE
        self.configure(bg=color, highlightbackground=ACCENT if self.active else (BORDER if color == base else SURFACE_3))
        for widget in self._labels:
            widget.configure(bg=color)
        for child in self.winfo_children():
            if isinstance(child, tk.Frame):
                child.configure(bg=color)
                for sub in child.winfo_children():
                    if isinstance(sub, tk.Button):
                        sub._bg = color
                        sub.configure(bg=color)


class ManagerWindow:
    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title("网络快捷切换 · 方案管理")
        self.win.configure(bg=BG)
        self.win.minsize(980, 660)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self.win.bind("<Escape>", lambda _e: self.hide())
        self.win.bind("<MouseWheel>", self._on_mousewheel, add="+")
        self._snapshot = None
        self._rows_key = None
        self._busy = False
        self._status_text = ""
        self._interactive_widgets: list[tk.Widget] = []
        self._startup = {}
        self._build()
        center_window(self.win, 1080, 680)

    def _build(self) -> None:
        outer = tk.Frame(self.win, bg=BG)
        outer.pack(fill="both", expand=True, padx=26, pady=20)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        title_box = tk.Frame(header, bg=BG)
        title_box.pack(side="left", fill="x", expand=True)
        title_row = tk.Frame(title_box, bg=BG)
        title_row.pack(fill="x", anchor="w")
        label(title_row, "网络快捷切换", fg=TEXT, size=20, weight="bold").pack(side="left")
        label(title_box, "IPv4 / DNS 方案管理", fg=MUTED, size=9).pack(
            anchor="w", pady=(4, 0)
        )
        right = tk.Frame(header, bg=BG)
        right.pack(side="right")
        self.admin_pill = label(right, "检测权限…", fg=MUTED, bg=SURFACE_2, size=8, padx=10, pady=5)
        self.admin_pill.pack(side="right", padx=(8, 0))

        adapter_bar = tk.Frame(outer, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        adapter_bar.pack(fill="x", pady=(16, 12))
        label(adapter_bar, "当前网卡", fg=MUTED, size=9, weight="bold").pack(side="left", padx=(14, 8), pady=12)
        self.adapter_combo = ttk.Combobox(
            adapter_bar,
            state="readonly",
            style="Dark.TCombobox",
            width=52,
            font=make_font(9),
        )
        self.adapter_combo.pack(side="left", pady=9)
        self.adapter_combo.bind("<<ComboboxSelected>>", self._on_adapter_selected)
        self._interactive_widgets.append(self.adapter_combo)
        FlatButton(adapter_bar, "刷新", self.app.request_refresh, bg=SURFACE_2, fg=TEXT, hover=BORDER, padx=12, pady=4).pack(
            side="left", padx=(8, 0)
        )
        self.current_label = label(adapter_bar, "正在读取…", fg=MUTED, size=9, anchor="e")
        self.current_label.pack(side="right", padx=(10, 14))

        list_head = tk.Frame(outer, bg=BG)
        list_head.pack(fill="x", pady=(2, 8))
        self.list_title = label(list_head, "方案列表", fg=TEXT, size=12, weight="bold")
        self.list_title.pack(side="left")
        self.count_label = label(list_head, "0 个", fg=FAINT, size=9)
        self.count_label.pack(side="left", padx=(8, 0))
        self.add_button = FlatButton(
            list_head,
            "＋ 新增方案",
            self.app.open_profile_dialog,
            bg=ACCENT_DARK,
            fg=TEXT,
            hover=ACCENT,
            padx=16,
            pady=6,
        )
        self.add_button.pack(side="right")
        self._interactive_widgets.append(self.add_button)

        table = tk.Frame(outer, bg=BG)
        header_row = tk.Frame(table, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        header_row.pack(fill="x")
        for column, title in enumerate(COLUMN_TITLES):
            if column == 1:
                header_row.grid_columnconfigure(column, weight=1, minsize=118)
            elif column == 0:
                header_row.grid_columnconfigure(column, minsize=42)
            elif column == 7:
                header_row.grid_columnconfigure(column, minsize=112)
            else:
                header_row.grid_columnconfigure(column, minsize={"2": 118, "3": 126, "4": 118, "5": 112, "6": 112}.get(str(column), 100))
            label(
                header_row,
                title,
                fg=MUTED,
                size=8,
                weight="bold",
                anchor="w" if column not in (0, 7) else "center",
            ).grid(row=0, column=column, sticky="ew", padx=(10 if column == 0 else 6, 6), pady=9)

        list_wrap = tk.Frame(table, bg=BG)
        list_wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(list_wrap, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar = ttk.Scrollbar(
            list_wrap,
            orient="vertical",
            command=self.canvas.yview,
            style="Dark.Vertical.TScrollbar",
        )
        self.scrollbar.pack(side="right", fill="y", padx=(6, 0))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.rows_frame = tk.Frame(self.canvas, bg=BG)
        self._canvas_window = self.canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind("<Configure>", self._on_rows_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.rows_frame.bind("<MouseWheel>", self._on_mousewheel)

        bottom = tk.Frame(outer, bg=BG)
        bottom.pack(side="bottom", fill="x", pady=(12, 0))
        footer = tk.Frame(bottom, bg=BG)
        footer.pack(fill="x")
        self.startup_var = tk.BooleanVar(value=False)
        self.startup_check = tk.Checkbutton(
            footer,
            text="开机自启（启动文件夹）",
            variable=self.startup_var,
            command=self.toggle_startup,
            bg=BG,
            fg=MUTED,
            activebackground=BG,
            activeforeground=TEXT,
            selectcolor=SURFACE_2,
            font=make_font(9),
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self.startup_check.pack(side="left", padx=(0, 0))
        self._interactive_widgets.append(self.startup_check)

        self.close_to_tray_var = tk.BooleanVar(value=bool(self.app.settings.close_to_tray))
        self.close_to_tray_check = tk.Checkbutton(
            footer,
            text="隐藏到托盘",
            variable=self.close_to_tray_var,
            command=self.toggle_close_to_tray,
            bg=BG,
            fg=MUTED,
            activebackground=BG,
            activeforeground=TEXT,
            selectcolor=SURFACE_2,
            font=make_font(9),
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self.close_to_tray_check.pack(side="left", padx=(18, 0))
        self._interactive_widgets.append(self.close_to_tray_check)

        FlatButton(footer, "恢复默认（自动获取）", self.app.restore_default, bg=SURFACE_2, fg=MUTED, hover=BORDER, padx=14, pady=5).pack(
            side="right"
        )
        self._refresh_startup_state()
        table.pack(fill="both", expand=True)

    # ---- geometry helpers ------------------------------------------------
    def _on_rows_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_scrollbar()

    def _on_canvas_configure(self, event):
        try:
            self.canvas.itemconfigure(self._canvas_window, width=event.width)
        except Exception:
            pass
        self._update_scrollbar()

    def _update_scrollbar(self) -> None:
        """内容不足一屏时隐藏滚动条，并在需要时重新显示。"""
        try:
            if not self.win.winfo_exists():
                return
            bbox = self.canvas.bbox("all")
            content_height = (bbox[3] - bbox[1]) if bbox else 0
            needed = content_height > self.canvas.winfo_height() + 1
            if needed:
                if not self.scrollbar.winfo_manager():
                    self.scrollbar.pack(side="right", fill="y", padx=(6, 0))
            else:
                if self.scrollbar.winfo_manager():
                    self.scrollbar.pack_forget()
                self.canvas.yview_moveto(0)
        except Exception:
            pass

    def _on_adapter_selected(self, _event=None):
        if self._snapshot is None:
            return
        index = self.adapter_combo.current()
        if 0 <= index < len(self._snapshot.adapters):
            adapter = self._snapshot.adapters[index]
            self.app.select_adapter(adapter.guid)

    def _on_mousewheel(self, event):
        if self.win.winfo_exists() and self.scrollbar.winfo_manager():
            try:
                self.canvas.yview_scroll(int(-event.delta / 120), "units")
            except Exception:
                pass

    # ---- state -----------------------------------------------------------
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

    def _on_close_request(self) -> None:
        if self.close_to_tray_var.get():
            self.hide()
        else:
            self.app.quit()

    def set_status(self, text: str, error: bool = False, busy: bool = False) -> None:
        """主界面已移除底部状态行；保留空实现供控制器统一调用。"""
        self._status_text = text

    def set_busy(self, text: str = "正在应用…", busy: bool = True) -> None:
        self._busy = busy
        self.set_status(text, busy=busy)
        try:
            self.add_button.configure(state="disabled" if busy else "normal")
            self.adapter_combo.configure(state="disabled" if busy else "readonly")
        except Exception:
            pass
        if self._snapshot:
            self._rebuild_rows(force=True)

    def _refresh_startup_state(self) -> None:
        try:
            info = self.app.get_startup_state()
            self._startup = info
            self.startup_var.set(bool(info.get("enabled")))
            if info.get("read_error"):
                fg = YELLOW
            else:
                fg = MUTED
            self.startup_check.configure(text="开机自启", fg=fg)
        except Exception as exc:
            self.startup_var.set(False)
            self.startup_check.configure(text="开机自启", fg=YELLOW)

    def toggle_startup(self) -> None:
        want = bool(self.startup_var.get())
        ok, info, error = self.app.set_startup(want)
        if not ok:
            self.startup_var.set(not want)
            self.set_status(error or "设置开机自启失败", error=True)
            messagebox.showerror("开机自启", error or "设置失败", parent=self.win)
            return
        self._startup = info
        self.startup_var.set(bool(info.get("enabled")))
        self._refresh_startup_state()
        self.set_status("已启用开机自启（任务管理器 → 启动 可见）" if want else "已禁用开机自启")

    def toggle_close_to_tray(self) -> None:
        want = bool(self.close_to_tray_var.get())
        if not self.app.set_close_to_tray(want):
            self.close_to_tray_var.set(not want)

    def delete_profile(self, profile_id: str) -> None:
        profile = self.app.get_profile(profile_id)
        if profile is None:
            return
        if not messagebox.askyesno(
            "删除方案",
            f"确定删除「{profile.name}」？\n\n只删除本工具里的方案，不会改动当前网卡配置。",
            parent=self.win,
        ):
            return
        ok, error = self.app.delete_profile(profile_id)
        if not ok:
            messagebox.showerror("删除方案", error or "删除失败", parent=self.win)

    # ---- rendering -------------------------------------------------------
    def _adapter_text(self, adapter: Adapter) -> str:
        state = "已连接" if adapter.is_up else "未连接"
        ip = adapter.ipv4 or "无 IPv4"
        return f"{adapter.name} · {ip} · {state} · {adapter.type_label}"

    def refresh(self, snapshot) -> None:
        self._snapshot = snapshot
        admin = self.app.is_admin
        self.admin_pill.configure(
            text="管理员" if admin else "普通用户",
            fg=TEXT if admin else YELLOW,
            bg=ACCENT_DARK if admin else SURFACE_2,
        )
        adapters = snapshot.adapters
        labels = [self._adapter_text(a) for a in adapters]
        if tuple(self.adapter_combo.cget("values")) != tuple(labels):
            self.adapter_combo.configure(values=labels)
        current_index = -1
        for index, adapter in enumerate(adapters):
            if snapshot.selected and adapter.if_index == snapshot.selected.if_index:
                current_index = index
                break
        if current_index >= 0:
            self.adapter_combo.current(current_index)
        else:
            self.adapter_combo.set("")
        if snapshot.selected:
            self.current_label.configure(text=snapshot.selected.current_summary())
        else:
            self.current_label.configure(text="未选择网卡")
        self._rebuild_rows()
        if self._busy:
            self.set_status("正在应用，请稍候…", busy=True)
        self._refresh_startup_state()

    def _rows_signature(self):
        snapshot = self._snapshot
        if snapshot is None:
            return None
        return (
            tuple((p.id, p.name, p.ip, p.mask, p.gateway, p.dns1, p.dns2) for p in self.app.settings.profiles),
            snapshot.active_profile_id,
            snapshot.selected.if_index if snapshot.selected else None,
            self._busy,
        )

    def _rebuild_rows(self, force: bool = False) -> None:
        signature = self._rows_signature()
        if not force and signature == self._rows_key:
            return
        self._rows_key = signature
        for child in self.rows_frame.winfo_children():
            child.destroy()
        profiles = self.app.settings.profiles
        self.count_label.configure(text=f"{len(profiles)} 个")
        active = self._snapshot.active_profile_id if self._snapshot else None
        if not profiles:
            empty = tk.Frame(self.rows_frame, bg=BG)
            empty.pack(fill="both", expand=True, pady=38)
            label(empty, "还没有方案", fg=TEXT, size=12, weight="bold").pack()
            label(empty, "点右上角「新增方案」，填入 IP、掩码、网关和 DNS。", fg=FAINT, size=9).pack(pady=(4, 12))
            FlatButton(
                empty,
                "＋ 新增第一个方案",
                self.app.open_profile_dialog,
                bg=SURFACE_2,
                fg=TEXT,
                hover=BORDER,
                padx=18,
                pady=7,
            ).pack()
            self.canvas.configure(scrollregion=(0, 0, 0, 80))
            self._update_scrollbar()
            return
        for profile in profiles:
            row = ProfileRow(self.rows_frame, self, profile, profile.id == active)
            row.pack(fill="x", pady=(0, 6))
            if self._busy:
                for widget in [row, *row._labels]:
                    try:
                        widget.configure(cursor="arrow")
                    except Exception:
                        pass
        self.rows_frame.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_scrollbar()
