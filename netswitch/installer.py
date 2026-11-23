"""安装/卸载：启动文件夹快捷方式 + 桌面目录链接/快捷方式。"""
from __future__ import annotations

import os
from pathlib import Path

from .shortcuts import (
    APP_NAME,
    DESKTOP_DIR_NAME,
    DESKTOP_FILE_NAME,
    LAUNCHER_NAME,
    LEGACY_DESKTOP_FILE_NAME,
    create_shortcut,
    ensure_directory_link,
    notify_shell_changed,
    read_shortcut,
    remove_startup_shortcut,
    set_startup_enabled,
    startup_shortcut_path,
    write_launcher,
)
from .win32 import app_icon_path, desktop_dir, ensure_app_executable, python_script


def install() -> dict:
    script = python_script()
    project = os.path.dirname(script)
    app_exe = ensure_app_executable()
    launcher = write_launcher(project, script, mode="--manage")
    startup_info = set_startup_enabled(True, project, script, force=True)
    desktop = Path(desktop_dir())
    dir_link = desktop / DESKTOP_DIR_NAME
    shortcut_path = desktop / DESKTOP_FILE_NAME
    dir_kind = ensure_directory_link(dir_link, Path(project))
    _remove_legacy_desktop_link(desktop / LEGACY_DESKTOP_FILE_NAME, launcher)
    _ensure_desktop_shortcut(shortcut_path, launcher, app_exe, project)
    notify_shell_changed()
    file_kind = "shortcut"
    return {
        "project": project,
        "script": script,
        "app_exe": app_exe,
        "icon": app_icon_path(),
        "launcher": str(launcher),
        "startup_lnk": str(startup_shortcut_path()),
        "startup": startup_info,
        "desktop_dir": str(dir_link),
        "desktop_dir_kind": dir_kind,
        "desktop_file": str(shortcut_path),
        "desktop_file_kind": file_kind,
    }


def _remove_legacy_desktop_link(path: Path, launcher: Path) -> None:
    """清理旧版桌面 .pyw 硬链接；只删指向本项目启动器的链接。"""
    if not path.exists() and not path.is_symlink():
        return
    try:
        same = os.path.samefile(str(path), str(launcher))
    except OSError:
        same = False
    if not same:
        return
    try:
        path.unlink()
    except OSError:
        pass


def _ensure_desktop_shortcut(path: Path, launcher: Path, app_exe: str, project: str) -> None:
    """创建指向项目内启动器的 .lnk；同名旧快捷方式可安全刷新。"""
    if path.exists():
        try:
            info = read_shortcut(path)
            arguments = info.get("arguments", "")
            ours = os.path.normcase(str(launcher)) in os.path.normcase(arguments)
            if not ours:
                # 项目换盘后旧快捷方式仍指向原目录的 启动.pyw；同名条目允许刷新。
                previous = arguments.strip().strip('"')
                ours = os.path.basename(previous) == LAUNCHER_NAME
        except OSError:
            ours = False
        if not ours:
            raise FileExistsError(f"桌面已存在同名快捷方式，但它不是本项目的：{path}")
    create_shortcut(
        path,
        app_exe,
        arguments=f'"{launcher}"',
        working_directory=project,
        description=APP_NAME,
        icon_location=app_icon_path() or app_exe,
    )


def _remove_desktop_link(path: Path, target: Path) -> str:
    if not path.exists() and not path.is_symlink():
        return "missing"
    try:
        same = os.path.samefile(str(path), str(target))
    except OSError:
        same = False
    if not same:
        raise OSError(f"拒绝删除：{path} 不是指向本项目的链接")
    try:
        if path.is_symlink() or not path.is_dir():
            path.unlink()
        else:
            path.rmdir()
    except OSError:
        # Junction 用 rmdir；如果失败再尝试 unlink。
        path.unlink()
    return "removed"


def _remove_desktop_shortcut(path: Path, launcher: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        info = read_shortcut(path)
    except OSError as exc:
        raise OSError(f"拒绝删除：无法读取桌面快捷方式 {path}") from exc
    if os.path.normcase(str(launcher)) not in os.path.normcase(info.get("arguments", "")):
        raise OSError(f"拒绝删除：{path} 不是指向本项目的快捷方式")
    path.unlink()
    return "removed"


def uninstall() -> dict:
    project = os.path.dirname(python_script())
    launcher = Path(project) / LAUNCHER_NAME
    desktop = Path(desktop_dir())
    result = {
        "startup": "removed",
        "desktop_dir": "missing",
        "desktop_shortcut": "missing",
        "legacy_desktop": "missing",
    }
    remove_startup_shortcut()
    for key, path, target in (
        ("desktop_dir", desktop / DESKTOP_DIR_NAME, Path(project)),
        ("legacy_desktop", desktop / LEGACY_DESKTOP_FILE_NAME, launcher),
    ):
        try:
            result[key] = _remove_desktop_link(path, target)
        except OSError as exc:
            result[key] = str(exc)
    try:
        result["desktop_shortcut"] = _remove_desktop_shortcut(desktop / DESKTOP_FILE_NAME, launcher)
    except OSError as exc:
        result["desktop_shortcut"] = str(exc)
    return result


def print_install_report(info: dict) -> None:
    startup = info.get("startup", {})
    print("已安装网络快捷切换：")
    print(f"  进程名：{os.path.basename(info.get('app_exe', ''))}")
    print(f"  启动项：{info['startup_lnk']}")
    print(f"    target={startup.get('target', '')}")
    print(f"    arguments={startup.get('arguments', '')}")
    print(f"    任务管理器可见：{'是' if startup.get('task_manager_visible') else '否'}")
    print(f"  桌面项目链接：{info['desktop_dir']}  [{info['desktop_dir_kind']}]")
    print(f"  桌面快捷方式：{info['desktop_file']}  [{info['desktop_file_kind']}]")
    print(f"  图标：{info.get('icon') or '（使用 exe 默认图标）'}")
    print(f"  启动器：{info['launcher']}")
    print("启动器使用相对路径，项目可整体移动；移动后重跑 --install 刷新桌面/启动项。")
    print("未复制任何项目文件；没有写入注册表 Run。")
