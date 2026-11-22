"""新增/编辑方案对话框（同一个对话框复用）。"""
from __future__ import annotations

import tkinter as tk

from .config import Profile, validate_profile_fields
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
    TEXT,
    FlatButton,
    center_window,
    entry,
    label,
    make_font,
)


class ProfileDialog:
    def __init__(self, app, parent, profile: Profile | None = None):
        self.app = app
        self.profile = profile
        self.editing = profile is not None
        self.errors: dict[str, tk.Label] = {}
        self.vars: dict[str, tk.StringVar] = {}
        self.clear_buttons: dict[str, tk.Label] = {}
        self.win = tk.Toplevel(parent)
        self.win.title("编辑方案" if self.editing else "新增方案")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda _e: self.close())
        self._build()
        center_window(self.win, 560, 670)
        try:
            self.win.grab_set()
        except tk.TclError:
            pass
        self.win.after(60, lambda: self.entries["name"].focus_set())
        self.win.after(100, self._raise)

    def _raise(self):
        try:
            self.win.lift()
            self.win.focus_force()
        except Exception:
            pass

    def _build(self) -> None:
        header = tk.Frame(self.win, bg=BG)
        header.pack(fill="x", padx=26, pady=(22, 10))
        label(header, "编辑方案" if self.editing else "新增方案", size=18, weight="bold").pack(anchor="w")
        label(
            header,
            "名称只用于本工具；IP、掩码、网关和 DNS 会写入所选网卡的 IPv4 属性。",
            fg=MUTED,
            size=9,
        ).pack(anchor="w", pady=(6, 0))

        footer = tk.Frame(self.win, bg=BG)
        footer.pack(side="bottom", fill="x", padx=24, pady=(10, 20))
        self.status = label(footer, "", fg=RED, size=9)
        self.status.pack(side="left")
        FlatButton(footer, "取消", self.close, bg=SURFACE_2, fg=TEXT, hover=BORDER, padx=20).pack(
            side="right", padx=(8, 0)
        )
        FlatButton(
            footer,
            "保存",
            self.save,
            bg=ACCENT_DARK,
            fg=TEXT,
            hover=ACCENT,
            padx=24,
        ).pack(side="right")

        body = tk.Frame(self.win, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        body.pack(fill="both", expand=True, padx=24, pady=8)
        form = tk.Frame(body, bg=SURFACE)
        form.pack(fill="both", expand=True, padx=18, pady=12)
        form.grid_columnconfigure(1, weight=1)

        defaults = {
            "name": self.profile.name if self.profile else "",
            "ip": self.profile.ip if self.profile else "",
            "mask": self.profile.mask if self.profile else "255.255.255.0",
            "gateway": self.profile.gateway if self.profile else "",
            "dns1": self.profile.dns1 if self.profile else "",
            "dns2": self.profile.dns2 if self.profile else "",
        }
        rows = [
            ("name", "名称", "例如：家里、公司"),
            ("ip", "IP 地址", "例如：192.168.1.50"),
            ("mask", "子网掩码", "例如：255.255.255.0"),
            ("gateway", "默认网关", "例如：192.168.1.1"),
            ("dns1", "DNS1", "例如：223.5.5.5"),
            ("dns2", "DNS2（可留空）", "可留空"),
        ]
        self.entries: dict[str, tk.Entry] = {}
        for index, (key, title, hint) in enumerate(rows):
            var = tk.StringVar(value=defaults[key])
            self.vars[key] = var
            label(form, title, size=10, weight="bold").grid(
                row=index * 2, column=0, sticky="w", padx=(0, 14), pady=(8 if index else 2, 2)
            )
            field = tk.Frame(
                form,
                bg=SURFACE_2,
                highlightthickness=1,
                highlightbackground=BORDER,
            )
            field.grid(row=index * 2, column=1, sticky="ew", pady=(8 if index else 2, 2))
            field.grid_columnconfigure(0, weight=1)
            widget = entry(field, textvariable=var, width=34)
            widget.configure(highlightthickness=0)
            widget.grid(row=0, column=0, sticky="ew", padx=(9, 2), pady=6)
            clear_button = tk.Label(
                field,
                text="×",
                fg=FAINT,
                bg=SURFACE_2,
                font=make_font(12),
                padx=5,
                cursor="hand2",
                takefocus=0,
            )
            clear_button.grid(row=0, column=1, sticky="e", padx=(0, 5))
            clear_button.bind("<Enter>", lambda _e, b=clear_button: b.configure(fg=TEXT))
            clear_button.bind("<Leave>", lambda _e, b=clear_button: b.configure(fg=FAINT))
            clear_button.bind("<Button-1>", lambda _e, k=key: self.clear_field(k))
            self.clear_buttons[key] = clear_button
            widget.bind("<FocusIn>", lambda _e, f=field: f.configure(highlightbackground=ACCENT))
            widget.bind("<FocusOut>", lambda _e, f=field: f.configure(highlightbackground=BORDER))
            self.entries[key] = widget
            hint_row = tk.Frame(form, bg=SURFACE)
            hint_row.grid(row=index * 2 + 1, column=1, sticky="ew", pady=(0, 2))
            label(hint_row, hint, fg=FAINT, size=8).pack(side="left")
            err = label(hint_row, "", fg=RED, size=8)
            err.pack(side="right")
            self.errors[key] = err
            widget.bind("<Return>", lambda _e: self.save())
            widget.bind("<KeyRelease>", lambda _e, k=key: self.errors[k].configure(text=""))


    def _collect(self) -> dict:
        return {key: var.get().strip() for key, var in self.vars.items()}

    def clear_field(self, key: str) -> None:
        self.vars[key].set("")
        self.errors[key].configure(text="")
        try:
            self.entries[key].focus_set()
        except Exception:
            pass

    def save(self) -> None:
        values = self._collect()
        normalized, errors = validate_profile_fields(
            values,
            self.app.settings.profiles,
            self.profile.id if self.profile else None,
        )
        for key, err_label in self.errors.items():
            err_label.configure(text=errors.get(key, ""))
        if errors:
            first = next(iter(errors))
            try:
                self.entries[first].focus_set()
            except Exception:
                pass
            self.status.configure(text="请检查标红的字段")
            return
        ok, extra = self.app.upsert_profile(
            self.profile.id if self.profile else None,
            normalized,
        )
        if not ok:
            for key, text in extra.items():
                if key in self.errors:
                    self.errors[key].configure(text=text)
            self.status.configure(text="保存失败，请检查输入")
            return
        self.close()

    def close(self) -> None:
        try:
            self.win.grab_release()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass
