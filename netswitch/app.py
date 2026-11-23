"""应用控制器：Tk 主线程、托盘线程、手动刷新、后台读取/应用。"""
from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox

from . import netcfg
from .compact import CompactWindow
from .config import (
    Profile,
    Settings,
    load_settings,
    make_profile,
    save_settings,
)
from .dialogs import ProfileDialog
from .icons import set_window_icon
from .manager import ManagerWindow
from .netinfo import (
    Adapter,
    configurable_adapters,
    detect_profile,
    enumerate_adapters,
    find_by_guid,
)
from .shortcuts import startup_state
from .tray import SingleInstance, TrayThread
from .ui_common import apply_theme
from .win32 import is_admin, python_script, set_app_user_model_id, set_dpi_aware
from .wlan import query_signals


@dataclass
class Snapshot:
    adapters: list[Adapter]
    selected: Adapter | None
    active_profile_id: str | None
    timestamp_text: str
    signals_available: bool = False


def _log(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


class Application:
    def __init__(self, mode: str = "manage", debug: bool = False, mutex: SingleInstance | None = None):
        self.mode = mode
        self.debug = debug
        self.mutex = mutex
        self.settings: Settings = load_settings()
        self.is_admin = is_admin()
        self.events: queue.Queue = queue.Queue()
        self.snapshot: Snapshot | None = None
        self.manager: ManagerWindow | None = None
        self.compact: CompactWindow | None = None
        self.dialog: ProfileDialog | None = None
        self.tray: TrayThread | None = None
        self._closing = False
        self._refreshing = False
        self._applying = False
        self._pump_id: str | None = None
        self._refresh_watchdog_id: str | None = None
        self._load_error_shown = False
        self._tray_icon_warning_shown = False

        set_dpi_aware()
        set_app_user_model_id("NetSwitch.Tool")
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("网络快捷切换")
        set_window_icon(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        apply_theme(self.root)
        try:
            from .win32 import get_dpi_for_system

            self.root.tk.call("tk", "scaling", max(1.0, get_dpi_for_system() / 72.0))
        except Exception:
            pass

        self._start_tray()
        if mode == "compact":
            self.show_compact()
        elif mode == "tray":
            pass
        else:
            self.show_manager()
        self._pump_id = self.root.after(100, self._pump)
        # 启动时读取一次；之后只在用户刷新或应用方案后读取，没有定时器。
        self.root.after(60, self.request_refresh)
        if self.settings.load_error:
            self.root.after(500, self._show_load_error)

    # ---- logging / tray -------------------------------------------------
    def _log(self, message: str) -> None:
        _log(self.debug, message)

    def _start_tray(self) -> None:
        tray = TrayThread(self.events)
        if not tray.start_and_wait(5.0):
            self.tray = None
            try:
                tray.stop(1.0)
            except Exception:
                pass
            self._log(f"tray failed: {tray.error}")
            self.mode = "manage"
            return
        self.tray = tray
        if tray.icon_error:
            self._log(f"tray icon warning: {tray.icon_error}")
        self._update_tray_state()

    def _update_tray_state(self) -> None:
        if not self.tray:
            return
        profiles = [(p.id, p.name) for p in self.settings.profiles]
        selected = self.snapshot.active_profile_id if self.snapshot else None
        profile_name = ""
        if selected:
            profile = self.get_profile(selected)
            if profile:
                profile_name = profile.name
        if self.snapshot and self.snapshot.selected:
            adapter = self.snapshot.selected
            if profile_name:
                mode = f"方案 {profile_name}"
            elif adapter.dhcp:
                mode = "自动获取（DHCP）"
            elif adapter.is_up:
                mode = "静态 IP（未匹配）"
            else:
                mode = "未连接"
            tip = f"网络快捷切换\n{adapter.name} · {mode}\n{adapter.ipv4 or '无 IPv4'}"
        else:
            tip = "网络快捷切换\n正在读取网卡…"
        self.tray.set_state(profiles, selected, tip)

    # ---- windows --------------------------------------------------------
    def show_manager(self) -> None:
        if self._closing:
            return
        if self.manager is None:
            self.manager = ManagerWindow(self)
        self.manager.show()
        if self.snapshot:
            self.manager.refresh(self.snapshot)
        if self.tray and self.tray.icon_error:
            self.manager.set_status("托盘图标不可用（Explorer 未运行？）；主界面仍可正常使用", error=False)

    def show_compact(self) -> None:
        if self._closing:
            return
        if self.compact is None:
            self.compact = CompactWindow(self)
        self.compact.show()
        if self.snapshot:
            self.compact.refresh(self.snapshot)

    def hide_all(self) -> None:
        if self.manager:
            self.manager.hide()
        if self.compact:
            self.compact.hide()

    def open_profile_dialog(self, profile_id: str | None = None) -> None:
        if self._closing:
            return
        if self.manager is None or not self.manager.is_visible():
            self.show_manager()
        if self.dialog is not None:
            try:
                self.dialog.win.lift()
                self.dialog.win.focus_force()
            except Exception:
                pass
            return
        profile = self.get_profile(profile_id) if profile_id else None
        parent = self.manager.win if self.manager else self.root
        self.dialog = ProfileDialog(self, parent, profile)
        try:
            self.dialog.win.bind("<Destroy>", self._on_dialog_destroy, add="+")
        except Exception:
            pass

    def _on_dialog_destroy(self, event=None) -> None:
        current = self.dialog.win if self.dialog else None
        if event is not None and getattr(event, "widget", None) is not current:
            return
        self.dialog = None

    # ---- profiles -------------------------------------------------------
    def get_profile(self, profile_id: str | None) -> Profile | None:
        if not profile_id:
            return None
        for profile in self.settings.profiles:
            if profile.id == profile_id:
                return profile
        return None

    def upsert_profile(self, profile_id: str | None, values: dict) -> tuple[bool, dict[str, str]]:
        if profile_id:
            profile = self.get_profile(profile_id)
            if profile is None:
                return False, {"name": "方案不存在"}
            updated = Profile(
                id=profile.id,
                name=values["name"],
                ip=values["ip"],
                mask=values["mask"],
                gateway=values["gateway"],
                dns1=values["dns1"],
                dns2=values.get("dns2", ""),
            )
            index = self.settings.profiles.index(profile)
            self.settings.profiles[index] = updated
            try:
                save_settings(self.settings)
            except Exception as exc:
                self.settings.profiles[index] = profile
                return False, {"name": f"保存 settings.json 失败：{exc}"}
            self._log(f"updated profile {profile.name}")
        else:
            profile = make_profile(values)
            self.settings.profiles.append(profile)
            try:
                save_settings(self.settings)
            except Exception as exc:
                self.settings.profiles.pop()
                return False, {"name": f"保存 settings.json 失败：{exc}"}
            self._log(f"added profile {profile.name}")
        self._update_tray_state()
        if self.manager and self.snapshot:
            self.manager.refresh(self.snapshot)
        self.request_refresh()
        return True, {}

    def delete_profile(self, profile_id: str) -> tuple[bool, str]:
        profile = self.get_profile(profile_id)
        if profile is None:
            return False, "方案不存在"
        index = self.settings.profiles.index(profile)
        removed = self.settings.profiles.pop(index)
        try:
            save_settings(self.settings)
        except Exception as exc:
            self.settings.profiles.insert(index, removed)
            return False, f"保存 settings.json 失败：{exc}"
        self._log(f"deleted profile {removed.name}")
        self._update_tray_state()
        if self.manager and self.snapshot:
            self.manager.refresh(self.snapshot)
        self.request_refresh()
        return True, ""

    def select_adapter(self, guid: str) -> None:
        if guid == self.settings.adapter_guid:
            return
        old = self.settings.adapter_guid
        self.settings.adapter_guid = guid
        try:
            save_settings(self.settings)
        except Exception as exc:
            self.settings.adapter_guid = old
            if self.manager:
                self.manager.set_status(f"保存网卡选择失败：{exc}", error=True)
            return
        self.request_refresh()

    # ---- refresh --------------------------------------------------------
    def request_refresh(self) -> None:
        if self._closing:
            return
        if self._applying:
            return
        if self._refreshing:
            return
        self._refreshing = True
        clicked_at = time.strftime("%H:%M:%S")
        if self.compact:
            self.compact.updated.configure(text=f"刷新 {clicked_at}")
        self._cancel_refresh_watchdog()
        self._refresh_watchdog_id = self.root.after(8000, self._on_refresh_timeout)
        threading.Thread(
            target=self._refresh_worker,
            args=(clicked_at,),
            name="net-switch-read",
            daemon=True,
        ).start()

    def _cancel_refresh_watchdog(self) -> None:
        if self._refresh_watchdog_id:
            try:
                self.root.after_cancel(self._refresh_watchdog_id)
            except Exception:
                pass
            self._refresh_watchdog_id = None

    def _on_refresh_timeout(self) -> None:
        self._refresh_watchdog_id = None
        if self._closing or not self._refreshing:
            return
        self._refreshing = False
        self._log("refresh timeout")
        self._status("刷新超时，请重新点击刷新", error=True)

    def _refresh_worker(self, timestamp_text: str) -> None:
        try:
            profiles = list(self.settings.profiles)
            wanted_guid = self.settings.adapter_guid
            adapters = enumerate_adapters()
            signals = query_signals(adapters)
            for adapter in adapters:
                adapter.signal = signals.get(adapter.if_index)
            selected = find_by_guid(wanted_guid, adapters)
            if selected is None or not selected.is_configurable:
                candidates = configurable_adapters(adapters)
                selected = candidates[0] if candidates else (adapters[0] if adapters else None)
            active = detect_profile(selected, profiles)
            snapshot = Snapshot(
                adapters=adapters,
                selected=selected,
                active_profile_id=active,
                timestamp_text=timestamp_text,
                signals_available=bool(signals),
            )
            self.events.put(("refresh_done", snapshot))
        except Exception as exc:
            self.events.put(("refresh_failed", str(exc)))

    def _on_refresh_done(self, snapshot: Snapshot) -> None:
        self._cancel_refresh_watchdog()
        self._refreshing = False
        if self._closing:
            return
        self.snapshot = snapshot
        if snapshot.selected and snapshot.selected.guid != self.settings.adapter_guid:
            self.settings.adapter_guid = snapshot.selected.guid
            try:
                save_settings(self.settings)
            except Exception as exc:
                self._log(f"save adapter guid failed: {exc}")
        self._update_tray_state()
        if self.manager:
            try:
                if not self.manager.is_visible():
                    self.manager.set_status("已刷新", busy=False)
                self.manager.refresh(snapshot)
            except Exception as exc:
                self._log(f"manager refresh failed: {exc}")
        if self.compact:
            try:
                self.compact.refresh(snapshot)
            except Exception as exc:
                self._log(f"compact refresh failed: {exc}")
        self._log(
            "refresh: "
            + (snapshot.selected.name if snapshot.selected else "no adapter")
            + f" active={snapshot.active_profile_id or '-'}"
        )

    def _on_refresh_failed(self, message: str) -> None:
        self._cancel_refresh_watchdog()
        self._refreshing = False
        if self._closing:
            return
        self._log(f"refresh failed: {message}")
        if self.manager:
            self.manager.set_status("读取网卡失败：" + message, error=True)
        if self.compact:
            self.compact.set_status("读取失败：" + message, error=True)
        if self.tray and not (self.manager and self.manager.is_visible()) and not (self.compact and self.compact.is_visible()):
            self.tray.notify("网络快捷切换", "读取网卡失败：" + message, error=True)

    # ---- apply ----------------------------------------------------------
    def apply_profile(self, profile_id: str, source: str = "ui") -> None:
        if self._closing:
            return
        if self._applying:
            self._status("正在应用另一个方案，请稍候…", error=False, busy=True)
            return
        profile = self.get_profile(profile_id)
        if profile is None:
            self._status("方案不存在", error=True)
            return
        adapter = self.snapshot.selected if self.snapshot else None
        if adapter is None:
            self._status("没有可用的网卡", error=True)
            return
        if self.snapshot and self.snapshot.active_profile_id == profile_id:
            self._status(f"「{profile.name}」已经是当前方案")
            return
        self._applying = True
        self._set_busy(f"正在应用「{profile.name}」… 如弹出 UAC 请允许", True)
        threading.Thread(
            target=self._apply_worker,
            args=("apply", adapter, profile, source),
            name="net-switch-apply",
            daemon=True,
        ).start()

    def restore_default(self, source: str = "ui") -> None:
        if self._closing:
            return
        if self._applying:
            self._status("正在应用，请稍候…", busy=True)
            return
        adapter = self.snapshot.selected if self.snapshot else None
        if adapter is None:
            self._status("没有可用的网卡", error=True)
            return
        if adapter.dhcp and not adapter.dns_static:
            self._status("当前已经是自动获取（DHCP）")
            return
        self._applying = True
        self._set_busy("正在恢复自动获取（DHCP）… 如弹出 UAC 请允许", True)
        threading.Thread(
            target=self._apply_worker,
            args=("restore", adapter, None, source),
            name="net-switch-restore",
            daemon=True,
        ).start()

    def _apply_worker(self, action: str, adapter: Adapter, profile: Profile | None, source: str) -> None:
        try:
            payload = netcfg.payload_restore(adapter) if action == "restore" else netcfg.payload_for_profile(adapter, profile)
            self._log(f"apply start action={action} adapter={adapter.name} if={adapter.if_index}")
            result = netcfg.perform(payload, self.debug)
            self.events.put(("apply_done", result, source))
        except Exception as exc:
            self.events.put(
                (
                    "apply_done",
                    netcfg.ApplyResult(
                        False,
                        f"应用失败：{exc}",
                        action,
                        profile.id if profile else None,
                        adapter,
                    ),
                    source,
                )
            )

    def _on_apply_done(self, result: netcfg.ApplyResult, source: str) -> None:
        self._applying = False
        self._log(f"apply done ok={result.ok} {result.message}")
        if self._closing:
            return
        if self.snapshot and result.adapter is not None:
            for index, adapter in enumerate(self.snapshot.adapters):
                if adapter.if_index == result.adapter.if_index:
                    result.adapter.signal = adapter.signal
                    self.snapshot.adapters[index] = result.adapter
                    break
            if self.snapshot.selected and self.snapshot.selected.if_index == result.adapter.if_index:
                self.snapshot.selected = result.adapter
        if result.ok:
            self.snapshot.active_profile_id = result.profile_id if result.action == "apply" else None
            self._update_tray_state()
            if self.manager:
                self.manager.set_busy("", False)
                if self.snapshot:
                    self.manager.refresh(self.snapshot)
            if self.compact:
                self.compact.set_busy("", False)
                if self.snapshot:
                    self.compact.refresh(self.snapshot)
            self._status(result.message, error=False)
            self._notify_if_hidden("网络快捷切换", result.message)
            self.root.after(120, self.request_refresh)
        else:
            if self.manager:
                self.manager.set_busy("", False)
                self.manager.set_status(result.message, error=True)
            if self.compact:
                self.compact.set_busy("", False)
                self.compact.set_status(result.message, error=True)
            self._show_error("切换失败", result.message)
            self.root.after(120, self.request_refresh)

    def _notify_if_hidden(self, title: str, text: str, error: bool = False) -> None:
        visible = bool(self.manager and self.manager.is_visible()) or bool(
            self.compact and self.compact.is_visible()
        )
        if not visible and self.tray:
            self.tray.notify(title, text, error=error)

    def _set_busy(self, text: str, busy: bool) -> None:
        if self.manager:
            self.manager.set_busy(text, busy)
        if self.compact:
            self.compact.set_busy(text, busy)
        self._status(text, busy=busy)

    def _status(self, text: str, error: bool = False, busy: bool = False) -> None:
        self._log(text)
        if self.manager:
            self.manager.set_status(text, error=error, busy=busy)
        if self.compact and text:
            if busy:
                self.compact.set_busy(text, True)
            else:
                self.compact.set_status(text, error=error)

    def _show_error(self, title: str, text: str) -> None:
        parent = self._message_parent()
        try:
            messagebox.showerror(title, text, parent=parent)
        except Exception:
            pass

    def _message_parent(self):
        if self.manager and self.manager.is_visible():
            return self.manager.win
        if self.compact and self.compact.is_visible():
            return self.compact.win
        return self.root

    # ---- settings / startup --------------------------------------------
    def get_startup_state(self) -> dict:
        return startup_state(python_script())

    def set_startup(self, enabled: bool) -> tuple[bool, dict, str]:
        try:
            info = self.app_set_startup(enabled)
            return True, info, ""
        except Exception as exc:
            return False, {}, f"设置开机自启失败：{exc}"

    def app_set_startup(self, enabled: bool) -> dict:
        from .shortcuts import set_startup_enabled

        project = os.path.dirname(python_script())
        return set_startup_enabled(enabled, project, python_script())

    def set_close_to_tray(self, enabled: bool) -> bool:
        enabled = bool(enabled)
        old = self.settings.close_to_tray
        if old == enabled:
            return True
        self.settings.close_to_tray = enabled
        try:
            save_settings(self.settings)
        except Exception as exc:
            self.settings.close_to_tray = old
            self._show_error("关闭行为", f"保存 settings.json 失败：{exc}")
            return False
        return True

    # ---- event loop -----------------------------------------------------
    def _pump(self) -> None:
        if self._closing:
            return
        for _ in range(80):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle_event(event)
            except Exception as exc:
                self._log(f"event error: {exc}")
                if self.debug:
                    import traceback

                    traceback.print_exc()
        if not self._closing:
            self._pump_id = self.root.after(100, self._pump)

    def _handle_event(self, event) -> None:
        if not isinstance(event, tuple) or not event:
            return
        kind = event[0]
        if kind == "refresh_done":
            self._on_refresh_done(event[1])
        elif kind == "refresh_failed":
            self._on_refresh_failed(event[1])
        elif kind == "apply_done":
            self._on_apply_done(event[1], event[2])
        elif kind == "open_manager":
            self.show_manager()
        elif kind == "open_compact":
            self.show_compact()
        elif kind == "apply":
            self.apply_profile(event[1], "tray")
        elif kind == "restore":
            self.restore_default("tray")
        elif kind == "refresh":
            self.request_refresh()
        elif kind == "quit":
            self.quit()
        elif kind == "tray_closed":
            if not self._closing:
                self._log("tray window closed unexpectedly")
                self.tray = None
                self.show_manager()

    def _show_load_error(self) -> None:
        if self._load_error_shown or not self.settings.load_error:
            return
        self._load_error_shown = True
        self._status(self.settings.load_error, error=True)
        if self.manager and self.manager.is_visible():
            messagebox.showwarning("settings.json", self.settings.load_error, parent=self.manager.win)
        elif self.tray:
            self.tray.notify("settings.json", self.settings.load_error, error=True)

    # ---- lifecycle ------------------------------------------------------
    def run(self) -> int:
        try:
            self.root.mainloop()
        finally:
            self._closing = True
            try:
                if self._pump_id:
                    self.root.after_cancel(self._pump_id)
            except Exception:
                pass
            self._cancel_refresh_watchdog()
            if self.tray:
                try:
                    self.tray.stop(2.0)
                except Exception:
                    pass
                self.tray = None
            try:
                self.root.destroy()
            except Exception:
                pass
            if self.mutex:
                self.mutex.close()
        return 0

    def quit(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._log("quit requested")
        self._cancel_refresh_watchdog()
        if self.tray:
            try:
                self.tray.stop(2.0)
            except Exception:
                pass
            self.tray = None
        try:
            self.root.quit()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        if self.mutex:
            try:
                self.mutex.close()
            except Exception:
                pass
