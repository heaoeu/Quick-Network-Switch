#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网络快捷切换：Windows 10/11 IPv4/DNS 方案切换工具。

只用 Python 标准库 + ctypes + tkinter。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

VERSION = "1.0.0"


def _print_once(debug: bool = False) -> int:
    from netswitch import netinfo

    try:
        adapters = netinfo.enumerate_adapters()
    except Exception as exc:
        print(f"读取网卡失败：{exc}")
        return 1
    configurable = netinfo.configurable_adapters(adapters)
    print(f"网络快捷切换 {VERSION}")
    print("可配置网卡：")
    if not configurable:
        print("  （没有检测到可配置的以太网/Wi-Fi 网卡）")
    for adapter in configurable:
        mode = "DHCP" if adapter.dhcp else "静态"
        print(
            f"  [{adapter.if_index}] {adapter.name} · {adapter.description}\n"
            f"      {adapter.status_label} · {mode} · IP {adapter.ipv4 or '—'} · "
            f"掩码 {adapter.mask or '—'} · 网关 {adapter.gateway or '—'} · "
            f"DNS {', '.join(adapter.dns) or '—'}"
        )
    from netswitch.config import load_settings

    settings = load_settings()
    print(f"方案（{len(settings.profiles)} 个）：")
    for profile in settings.profiles:
        print(
            f"  {profile.name}: {profile.ip}/{profile.mask} gw={profile.gateway} "
            f"dns={profile.dns1}{', ' + profile.dns2 if profile.dns2 else ''}"
        )
    if settings.load_error:
        print(settings.load_error)
    return 0


def _elevated_apply(token: str, debug: bool) -> int:
    from netswitch import netcfg

    try:
        payload = netcfg.decode_payload(token)
    except Exception as exc:
        if debug:
            print(f"提权任务解析失败：{exc}")
        return 2
    result = netcfg.apply_payload(payload, debug)
    if debug:
        print(f"提权任务结果：{'成功' if result.ok else '失败'} · {result.message}")
    return 0 if result.ok else 1


def _install(debug: bool) -> int:
    from netswitch.installer import install, print_install_report

    try:
        info = install()
    except Exception as exc:
        print(f"安装失败：{exc}")
        return 1
    print_install_report(info)
    return 0


def _uninstall(debug: bool) -> int:
    from netswitch.installer import uninstall

    try:
        result = uninstall()
    except Exception as exc:
        print(f"卸载失败：{exc}")
        return 1
    print("已移除启动项和桌面链接（项目文件保留）：")
    for key, value in result.items():
        print(f"  {key}: {value}")
    return 0


def _quit_running() -> int:
    from netswitch.tray import WM_APP_QUIT, find_tray_window
    from netswitch.win32 import user32

    hwnd = find_tray_window()
    if not hwnd:
        print("没有正在运行的网络快捷切换实例。")
        return 0
    user32.PostMessageW(hwnd, WM_APP_QUIT, 0, 0)
    print("已通知正在运行的实例退出。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="net_switch.py",
        description="Windows 10/11 IPv4 / DNS 方案快速切换（零第三方依赖）",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--manage", action="store_const", const="manage", dest="mode", help="打开主界面（默认）")
    modes.add_argument("--panel", action="store_const", const="compact", dest="mode", help="只打开简洁面板")
    modes.add_argument("--tray", action="store_const", const="tray", dest="mode", help="启动后只驻留托盘")
    parser.add_argument("--install", action="store_true", help="创建启动文件夹快捷方式和桌面链接")
    parser.add_argument("--uninstall", action="store_true", help="移除启动项和桌面链接（保留项目）")
    parser.add_argument("--quit", action="store_true", help="让正在运行的实例退出")
    parser.add_argument("--once", action="store_true", help="读取并打印当前网卡/方案后退出")
    parser.add_argument("--elevated-apply", metavar="TOKEN", default="", help=argparse.SUPPRESS)
    parser.add_argument("--debug", action="store_true", help="只在控制台输出诊断信息（不写日志文件）")
    parser.add_argument("--version", action="version", version=f"网络快捷切换 {VERSION}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.elevated_apply:
        return _elevated_apply(args.elevated_apply, args.debug)
    if args.install:
        return _install(args.debug)
    if args.uninstall:
        return _uninstall(args.debug)
    if args.quit:
        return _quit_running()
    if args.once:
        return _print_once(args.debug)

    mode = args.mode or "manage"
    from netswitch.tray import SingleInstance, notify_existing_instance

    mutex = SingleInstance()
    if mutex.already_exists:
        if mode == "compact":
            notify_existing_instance("compact")
        elif mode == "manage":
            notify_existing_instance("manager")
        mutex.close()
        return 0

    try:
        from netswitch.app import Application

        app = Application(mode=mode, debug=args.debug, mutex=mutex)
        return app.run()
    except Exception as exc:
        if args.debug:
            import traceback

            traceback.print_exc()
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, f"网络快捷切换启动失败：\n{exc}", "网络快捷切换", 0x00000010
            )
        except Exception:
            pass
        mutex.close()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
