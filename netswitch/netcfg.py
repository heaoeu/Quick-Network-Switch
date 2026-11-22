"""IPv4/DNS 配置写入、UAC 提权与结果校验。

Windows 修改静态 IP / DNS 需要管理员权限。GUI 进程平时以普通权限常驻；
点「应用」时只把一个很小的 JSON 任务通过 ShellExecuteExW(runas) 交给
pythonw.exe 子进程执行，主进程保持响应。没有注册表 Run、没有服务、没有日志。
"""
from __future__ import annotations

import base64
import ctypes
import ipaddress
import json
import os
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass

from .config import Profile
from .netinfo import Adapter, find_adapter, profile_matches
from .win32 import (
    CREATE_NO_WINDOW,
    ERROR_CANCELLED,
    SW_HIDE,
    is_admin,
    kernel32,
    python_script,
    pythonw_path,
    shell32,
    win_error_text,
)

SEE_MASK_NOCLOSEPROCESS = 0x00000040
INFINITE = 0xFFFFFFFF
WAIT_TIMEOUT = 0x00000102


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


shell32.ShellExecuteExW.restype = wintypes.BOOL
shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]


@dataclass
class ApplyResult:
    ok: bool
    message: str
    action: str
    profile_id: str | None = None
    adapter: Adapter | None = None


def _netsh_path() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = os.path.join(root, "System32", "netsh.exe")
    return candidate if os.path.isfile(candidate) else "netsh.exe"


def _powershell_path() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return candidate if os.path.isfile(candidate) else "powershell.exe"


def _decode_output(raw: bytes) -> str:
    for encoding in ("mbcs", "utf-8", "utf-16-le"):
        try:
            text = raw.decode(encoding, "replace")
        except Exception:
            continue
        if text:
            return text.strip()
    return ""


def _run(command: list[str], debug: bool = False) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            timeout=35,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    output = "\n".join(
        part for part in (_decode_output(proc.stdout), _decode_output(proc.stderr)) if part
    ).strip()
    if debug:
        print(f"[netcfg] {command[0]} exit={proc.returncode} {output[:500]}")
    return proc.returncode == 0, output


def _ps_dns_static(if_index: int, servers: list[str], debug: bool = False) -> tuple[bool, str]:
    quoted = ",".join("'" + ipaddress.IPv4Address(item).compressed + "'" for item in servers)
    script = (
        "$ErrorActionPreference='Stop'; "
        f"Set-DnsClientServerAddress -InterfaceIndex {int(if_index)} "
        f"-ServerAddresses @({quoted})"
    )
    return _run(
        [
            _powershell_path(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        debug,
    )


def _ps_dns_reset(if_index: int, debug: bool = False) -> tuple[bool, str]:
    script = (
        "$ErrorActionPreference='Stop'; "
        f"Set-DnsClientServerAddress -InterfaceIndex {int(if_index)} -ResetServerAddresses"
    )
    return _run(
        [
            _powershell_path(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        debug,
    )


def _netsh_dns_static(adapter: Adapter, servers: list[str], debug: bool = False) -> tuple[bool, str]:
    # PowerShell 失败时的兜底。先切回 DHCP DNS 清空旧列表，再写静态列表。
    _run(
        [
            _netsh_path(),
            "interface",
            "ipv4",
            "set",
            "dnsservers",
            f"name={adapter.name}",
            "source=dhcp",
        ],
        debug,
    )
    ok, output = _run(
        [
            _netsh_path(),
            "interface",
            "ipv4",
            "set",
            "dnsservers",
            f"name={adapter.name}",
            "static",
            servers[0],
            "primary",
        ],
        debug,
    )
    if not ok:
        return False, output
    if len(servers) > 1:
        ok2, out2 = _run(
            [
                _netsh_path(),
                "interface",
                "ipv4",
                "add",
                "dnsservers",
                f"name={adapter.name}",
                "address=" + servers[1],
                "index=2",
            ],
            debug,
        )
        if not ok2:
            return False, out2
    return True, ""


def _netsh_dns_dhcp(adapter: Adapter, debug: bool = False) -> tuple[bool, str]:
    return _run(
        [
            _netsh_path(),
            "interface",
            "ipv4",
            "set",
            "dnsservers",
            f"name={adapter.name}",
            "source=dhcp",
        ],
        debug,
    )


def _set_static_ip(adapter: Adapter, ip: str, mask: str, gateway: str, debug: bool = False) -> tuple[bool, str]:
    return _run(
        [
            _netsh_path(),
            "interface",
            "ipv4",
            "set",
            "address",
            f"name={adapter.name}",
            "static",
            ip,
            mask,
            gateway,
        ],
        debug,
    )


def _set_dhcp_ip(adapter: Adapter, debug: bool = False) -> tuple[bool, str]:
    return _run(
        [
            _netsh_path(),
            "interface",
            "ipv4",
            "set",
            "address",
            f"name={adapter.name}",
            "source=dhcp",
        ],
        debug,
    )


def _valid_ipv4(value: str) -> str:
    return str(ipaddress.IPv4Address(str(value).strip()))


def _valid_mask(value: str) -> str:
    network = ipaddress.IPv4Network(f"0.0.0.0/{str(value).strip()}")
    if network.prefixlen < 1:
        raise ValueError("mask /0")
    return str(network.netmask)


def _validate_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("任务格式错误")
    action = str(payload.get("action", ""))
    if action not in ("apply", "restore"):
        raise ValueError("未知操作")
    try:
        if_index = int(payload.get("if_index", 0))
    except (TypeError, ValueError):
        raise ValueError("网卡索引无效") from None
    if if_index <= 0:
        raise ValueError("网卡索引无效")
    clean = {"action": action, "if_index": if_index, "profile_id": payload.get("profile_id")}
    if action == "apply":
        clean["ip"] = _valid_ipv4(payload.get("ip", ""))
        clean["mask"] = _valid_mask(payload.get("mask", ""))
        clean["gateway"] = _valid_ipv4(payload.get("gateway", ""))
        clean["dns1"] = _valid_ipv4(payload.get("dns1", ""))
        dns2 = str(payload.get("dns2", "") or "").strip()
        clean["dns2"] = _valid_ipv4(dns2) if dns2 else ""
        if clean["dns2"] and clean["dns2"] == clean["dns1"]:
            raise ValueError("DNS2 不能与 DNS1 相同")
        network = ipaddress.IPv4Network(f"{clean['ip']}/{clean['mask']}", strict=False)
        ip_obj = ipaddress.IPv4Address(clean["ip"])
        if ip_obj not in network:
            raise ValueError("IP 不在掩码对应的子网内")
        if network.prefixlen <= 30 and ip_obj in (network.network_address, network.broadcast_address):
            raise ValueError("不能使用子网网络地址或广播地址作为主机 IP")
        gw_obj = ipaddress.IPv4Address(clean["gateway"])
        if gw_obj not in network:
            raise ValueError("网关不在 IP 所在子网内")
        if network.prefixlen <= 30 and gw_obj in (network.network_address, network.broadcast_address):
            raise ValueError("网关不能是子网网络地址或广播地址")
        for key in ("ip", "gateway", "dns1", "dns2"):
            if clean[key]:
                ip = ipaddress.IPv4Address(clean[key])
                if ip.is_unspecified or ip.is_loopback or ip.is_multicast:
                    raise ValueError(f"{key} 地址不可用")
    return clean


def payload_for_profile(adapter: Adapter, profile: Profile) -> dict:
    return {
        "action": "apply",
        "if_index": adapter.if_index,
        "profile_id": profile.id,
        "ip": profile.ip,
        "mask": profile.mask,
        "gateway": profile.gateway,
        "dns1": profile.dns1,
        "dns2": profile.dns2,
    }


def payload_restore(adapter: Adapter) -> dict:
    return {"action": "restore", "if_index": adapter.if_index, "profile_id": None}


def encode_payload(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_payload(token: str) -> dict:
    text = str(token).strip()
    text += "=" * (-len(text) % 4)
    raw = base64.urlsafe_b64decode(text.encode("ascii"))
    return _validate_payload(json.loads(raw.decode("utf-8")))


def _expected_static(adapter: Adapter, payload: dict) -> bool:
    try:
        return (
            not adapter.dhcp
            and adapter.ipv4 == payload["ip"]
            and adapter.mask == payload["mask"]
            and adapter.gateway == payload["gateway"]
            and adapter.dns1 == payload["dns1"]
            and adapter.dns2 == payload.get("dns2", "")
        )
    except Exception:
        return False


def verify_payload(payload: dict, retries: int = 12, delay: float = 0.3) -> tuple[bool, Adapter | None, str]:
    """修改后短时间内轮询验证（只在操作结束后运行，不是常驻轮询）。"""
    if payload.get("action") == "restore":
        # DHCP 重新获取地址通常要 1–3 秒，给足租约时间再判定失败。
        retries = max(retries, 30)
        delay = max(delay, 0.3)
    last: Adapter | None = None
    for attempt in range(retries):
        adapter = find_adapter(int(payload["if_index"]))
        if adapter is not None:
            last = adapter
            if payload["action"] == "restore":
                if adapter.dhcp and not adapter.dns_static and (adapter.ipv4 or not adapter.is_up):
                    return True, adapter, ""
            elif _expected_static(adapter, payload):
                return True, adapter, ""
        if attempt + 1 < retries:
            time.sleep(delay)
    if last is None:
        return False, None, "找不到目标网卡（可能已被禁用或拔出）"
    if payload["action"] == "restore":
        if last.dhcp and not last.dns_static and not last.ipv4:
            return False, last, "已切换为 DHCP，但网卡尚未取得 IPv4 地址"
        return False, last, "网卡尚未切换到自动获取（DHCP）"
    return False, last, "Windows 中的 IPv4/DNS 值与方案不一致"


def apply_payload(payload: dict, debug: bool = False) -> ApplyResult:
    """在拥有管理员权限的进程中真正执行配置写入。"""
    try:
        clean = _validate_payload(payload)
    except Exception as exc:
        return ApplyResult(False, str(exc), str(payload.get("action", "")), payload.get("profile_id"))
    adapter = find_adapter(int(clean["if_index"]))
    if adapter is None:
        return ApplyResult(False, "找不到目标网卡（可能已被禁用或拔出）", clean["action"], clean.get("profile_id"))
    if clean["action"] == "restore":
        if adapter.dhcp and not adapter.dns_static:
            return ApplyResult(True, "已经是自动获取（DHCP）", "restore", None, adapter)
        ok, output = _set_dhcp_ip(adapter, debug)
        if not ok:
            return ApplyResult(False, "设置自动获取 IP 失败：" + (output or "netsh 返回错误"), "restore", None, adapter)
        ok, output = _ps_dns_reset(adapter.if_index, debug)
        if not ok:
            ok, output = _netsh_dns_dhcp(adapter, debug)
        if not ok:
            return ApplyResult(False, "IP 已切换为 DHCP，但重置 DNS 失败：" + (output or "PowerShell/netsh 返回错误"), "restore", None, adapter)
        good, fresh, message = verify_payload(clean)
        return ApplyResult(good, "已恢复自动获取（DHCP）" if good else message, "restore", None, fresh)

    if profile_matches(adapter, _payload_as_profile(clean)):
        return ApplyResult(True, "当前配置已经是该方案", "apply", clean.get("profile_id"), adapter)
    ok, output = _set_static_ip(adapter, clean["ip"], clean["mask"], clean["gateway"], debug)
    if not ok:
        return ApplyResult(False, "设置静态 IP 失败：" + (output or "netsh 返回错误"), "apply", clean.get("profile_id"), adapter)
    servers = [clean["dns1"]] + ([clean["dns2"]] if clean["dns2"] else [])
    ok, output = _ps_dns_static(adapter.if_index, servers, debug)
    if not ok:
        ok, output = _netsh_dns_static(adapter, servers, debug)
    if not ok:
        return ApplyResult(False, "IP 已设置，但设置 DNS 失败：" + (output or "PowerShell/netsh 返回错误"), "apply", clean.get("profile_id"), adapter)
    good, fresh, message = verify_payload(clean)
    return ApplyResult(good, "方案已应用" if good else message, "apply", clean.get("profile_id"), fresh)


def _payload_as_profile(payload: dict) -> Profile:
    return Profile(
        id=str(payload.get("profile_id") or ""),
        name="",
        ip=payload["ip"],
        mask=payload["mask"],
        gateway=payload["gateway"],
        dns1=payload["dns1"],
        dns2=payload.get("dns2", ""),
    )


def run_elevated(payload: dict, debug: bool = False) -> tuple[bool, int | None, str]:
    """通过 UAC 启动 pythonw --elevated-apply，并等待其结束。"""
    # ShellExecuteEx 在后台线程调用时，先初始化 COM 更稳妥。
    try:
        ctypes.windll.ole32.CoInitializeEx(None, 2)
    except Exception:
        pass
    token = encode_payload(payload)
    script = python_script()
    executable = pythonw_path()
    params = f'"{script}" --elevated-apply={token}'
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.hwnd = None
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = params
    info.lpDirectory = os.path.dirname(script)
    info.nShow = SW_HIDE
    ctypes.set_last_error(0)
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.get_last_error()
        if code == ERROR_CANCELLED:
            return False, None, "已取消管理员授权，网络配置未修改。"
        return False, None, f"无法启动管理员进程：{win_error_text(code)}"
    if not info.hProcess:
        return False, None, "管理员进程未返回句柄"
    exit_code: int | None = None
    try:
        wait = kernel32.WaitForSingleObject(info.hProcess, 180_000)
        if wait == WAIT_TIMEOUT:
            return False, None, "等待管理员进程超时（180 秒）"
        code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            exit_code = int(code.value)
    finally:
        kernel32.CloseHandle(info.hProcess)
    if debug:
        print(f"[netcfg] elevated exit={exit_code}")
    return exit_code == 0, exit_code, ""


def perform(payload: dict, debug: bool = False) -> ApplyResult:
    """普通权限入口：管理员直接执行；否则 UAC 子进程 + 父进程复核。"""
    action = str(payload.get("action", ""))
    profile_id = payload.get("profile_id")
    # 已经满足时不弹 UAC（例如托盘双击/刷新竞态）。
    try:
        clean = _validate_payload(payload)
        adapter_now = find_adapter(int(clean["if_index"]))
        if adapter_now is not None:
            if clean["action"] == "restore" and adapter_now.dhcp and not adapter_now.dns_static:
                return ApplyResult(True, "已经是自动获取（DHCP）", "restore", None, adapter_now)
            if clean["action"] == "apply" and profile_matches(adapter_now, _payload_as_profile(clean)):
                return ApplyResult(True, "当前配置已经是该方案", "apply", clean.get("profile_id"), adapter_now)
    except Exception:
        pass
    if is_admin():
        return apply_payload(payload, debug)
    launched, exit_code, error = run_elevated(payload, debug)
    if not launched:
        return ApplyResult(False, error, action, profile_id)
    # 父进程不能只相信子进程退出码，再读一次 Windows 的真实配置。
    good, adapter, message = verify_payload(payload, retries=8, delay=0.25)
    if good:
        return ApplyResult(
            True,
            "已恢复自动获取（DHCP）" if action == "restore" else "方案已应用",
            action,
            profile_id,
            adapter,
        )
    reason = message
    if exit_code not in (0, None):
        reason = f"{reason}（管理员子进程退出码 {exit_code}）"
    return ApplyResult(False, reason, action, profile_id, adapter)
