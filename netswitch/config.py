"""方案数据模型与 settings.json 读写。

settings.json 是配置，不是日志：只保存当前网卡和用户方案。
写入采用同目录临时文件 + os.replace，避免断电/崩溃留下半个 JSON。
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_DIR / "settings.json"


@dataclass
class Profile:
    id: str
    name: str
    ip: str
    mask: str
    gateway: str
    dns1: str
    dns2: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "ip": self.ip,
            "mask": self.mask,
            "gateway": self.gateway,
            "dns1": self.dns1,
            "dns2": self.dns2,
        }

    def copy_with(self, **changes) -> "Profile":
        data = self.to_dict()
        data.update(changes)
        return Profile(**data)


@dataclass
class Settings:
    close_to_tray: bool = True
    adapter_guid: str = ""
    profiles: list[Profile] = field(default_factory=list)
    load_error: str = ""
    path: Path = SETTINGS_PATH


def _new_id() -> str:
    return "p_" + uuid.uuid4().hex[:10]


def profile_from_dict(raw: dict, *, make_id: bool = True) -> Profile | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name", "")).strip()
    if not name:
        return None
    pid = str(raw.get("id", "")).strip()
    if not pid and make_id:
        pid = _new_id()
    if not pid:
        return None
    return Profile(
        id=pid,
        name=name,
        ip=str(raw.get("ip", "")).strip(),
        mask=str(raw.get("mask", "")).strip(),
        gateway=str(raw.get("gateway", "")).strip(),
        dns1=str(raw.get("dns1", "")).strip(),
        dns2=str(raw.get("dns2", "")).strip(),
    )


def load_settings(path: Path | None = None) -> Settings:
    target = Path(path) if path else SETTINGS_PATH
    settings = Settings(path=target)
    if not target.is_file():
        return settings
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        settings.load_error = f"settings.json 读取失败：{exc}"
        return settings
    if not isinstance(data, dict):
        settings.load_error = "settings.json 顶层必须是对象"
        return settings
    close_to_tray = data.get("close_to_tray", True)
    settings.close_to_tray = close_to_tray if isinstance(close_to_tray, bool) else True
    settings.adapter_guid = str(data.get("adapter_guid", "")).strip()
    seen: set[str] = set()
    profiles: list[Profile] = []
    raw_profiles = data.get("profiles", [])
    if isinstance(raw_profiles, list):
        for raw in raw_profiles:
            profile = profile_from_dict(raw)
            if profile is None:
                continue
            if profile.id in seen:
                profile.id = _new_id()
            seen.add(profile.id)
            profiles.append(profile)
    settings.profiles = profiles
    return settings


def save_settings(settings: Settings) -> None:
    data = {
        "version": 1,
        "close_to_tray": bool(settings.close_to_tray),
        "adapter_guid": settings.adapter_guid,
        "profiles": [p.to_dict() for p in settings.profiles],
    }
    target = settings.path
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)


_IP_ERROR = "请输入有效的 IPv4 地址"
_NAME_BAD = re.compile(r"[\x00-\x1f\x7f]")


def _clean_ip(value: str) -> tuple[str, Exception | None]:
    text = (value or "").strip()
    try:
        return str(ipaddress.IPv4Address(text)), None
    except Exception as exc:
        return text, exc


def _valid_host_address(value: str) -> bool:
    try:
        ip = ipaddress.IPv4Address(value)
        return not (
            ip.is_unspecified
            or ip.is_loopback
            or ip.is_multicast
            or ip.is_reserved
        )
    except Exception:
        return False


def validate_profile_fields(values: dict, profiles: list[Profile], editing_id: str | None = None) -> tuple[dict, dict[str, str]]:
    """校验新增/编辑表单。返回 (规范化字段, 字段错误)。

    按需求：名称、IP、子网掩码、默认网关、DNS1 必填，DNS2 可空。
    """
    errors: dict[str, str] = {}
    name = str(values.get("name", "")).strip()
    if not name:
        errors["name"] = "名称不能为空"
    elif len(name) > 40:
        errors["name"] = "名称不能超过 40 个字符"
    elif _NAME_BAD.search(name):
        errors["name"] = "名称不能包含控制字符"
    else:
        for profile in profiles:
            if profile.id != editing_id and profile.name.casefold() == name.casefold():
                errors["name"] = "已存在同名方案"
                break

    ip, ip_exc = _clean_ip(str(values.get("ip", "")))
    if ip_exc or not _valid_host_address(ip):
        errors["ip"] = _IP_ERROR

    mask_text = str(values.get("mask", "")).strip()
    network = None
    try:
        network = ipaddress.IPv4Network(f"0.0.0.0/{mask_text}")
        if network.prefixlen < 1:
            raise ValueError
        mask = str(network.netmask)
    except Exception:
        mask = mask_text
        errors["mask"] = "请输入连续的子网掩码，例如 255.255.255.0"
    subnet = None
    if mask and "mask" not in errors and "ip" not in errors:
        try:
            subnet = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
            ip_obj = ipaddress.IPv4Address(ip)
            if subnet.prefixlen <= 30 and ip_obj in (subnet.network_address, subnet.broadcast_address):
                errors["ip"] = "不能把子网网络地址或广播地址用作主机 IP"
        except Exception:
            subnet = None

    gateway, gw_exc = _clean_ip(str(values.get("gateway", "")))
    if gw_exc or not _valid_host_address(gateway):
        errors["gateway"] = "请输入有效的默认网关"
    elif subnet is not None and "mask" not in errors:
        # 网关通常与 IP 同网段；把明显不在同一子网的输入提示出来。
        try:
            gw_obj = ipaddress.IPv4Address(gateway)
            if gw_obj not in subnet:
                errors["gateway"] = f"网关不在 {subnet} 子网内"
            elif subnet.prefixlen <= 30 and gw_obj in (subnet.network_address, subnet.broadcast_address):
                errors["gateway"] = "网关不能是子网网络地址或广播地址"
        except Exception:
            pass

    dns1, dns1_exc = _clean_ip(str(values.get("dns1", "")))
    if dns1_exc or not _valid_host_address(dns1):
        errors["dns1"] = "请输入有效的 DNS1"

    dns2_text = str(values.get("dns2", "")).strip()
    dns2 = ""
    if dns2_text:
        dns2, dns2_exc = _clean_ip(dns2_text)
        if dns2_exc or not _valid_host_address(dns2):
            errors["dns2"] = "DNS2 可留空，或填写有效的 IPv4 地址"
        elif dns2 == dns1:
            errors["dns2"] = "DNS2 不能与 DNS1 相同"

    normalized = {
        "name": name,
        "ip": ip,
        "mask": mask,
        "gateway": gateway,
        "dns1": dns1,
        "dns2": dns2,
    }
    return normalized, errors


def make_profile(values: dict) -> Profile:
    return Profile(
        id=_new_id(),
        name=values["name"],
        ip=values["ip"],
        mask=values["mask"],
        gateway=values["gateway"],
        dns1=values["dns1"],
        dns2=values.get("dns2", ""),
    )
