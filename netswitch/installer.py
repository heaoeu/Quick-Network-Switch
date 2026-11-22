"""安装/卸载：启动文件夹快捷方式 + 桌面目录链接/文件链接。"""
from __future__ import annotations

import os
from pathlib import Path

from .shortcuts import (
    DESKTOP_DIR_NAME,
    DESKTOP_FILE_NAME,
    LAUNCHER_NAME,
    ensure_directory_link,
    ensure_file_link,
    remove_startup_shortcut,
    set_startup_enabled,
    startup_shortcut_path,
    write_launcher,
)
from .win32 import desktop_dir, ensure_app_executable, python_script


def install() -> dict:
    script = python_script()
    project = os.path.dirname(script)
    app_exe = ensure_app_executable()
    launcher = write_launcher(project, script, mode="--manage")
    startup_info = set_startup_enabled(True, project, script)
    desktop = Path(desktop_dir())
    dir_link = desktop / DESKTOP_DIR_NAME
    file_link = desktop / DESKTOP_FILE_NAME
    dir_kind = ensure_directory_link(dir_link, Path(project))
    file_kind = ensure_file_link(file_link, launcher)
    return {
        "project": project,
        "script": script,
        "app_exe": app_exe,
        "launcher": str(launcher),
        "startup_lnk": str(startup_shortcut_path()),
        "startup": startup_info,
        "desktop_dir": str(dir_link),
        "desktop_dir_kind": dir_kind,
        "desktop_file": str(file_link),
        "desktop_file_kind": file_kind,
    }


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


def uninstall() -> dict:
    project = os.path.dirname(python_script())
    launcher = Path(project) / LAUNCHER_NAME
    desktop = Path(desktop_dir())
    result = {"startup": "removed", "desktop_dir": "missing", "desktop_file": "missing"}
    remove_startup_shortcut()
    for key, path, target in (
        ("desktop_dir", desktop / DESKTOP_DIR_NAME, Path(project)),
        ("desktop_file", desktop / DESKTOP_FILE_NAME, launcher),
    ):
        try:
            result[key] = _remove_desktop_link(path, target)
        except OSError as exc:
            result[key] = str(exc)
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
    print(f"  桌面启动链接：{info['desktop_file']}  [{info['desktop_file_kind']}]")
    print(f"  启动器：{info['launcher']}")
    print("未复制任何项目文件；没有写入注册表 Run。")
