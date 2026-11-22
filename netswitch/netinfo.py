"""IPv4 网卡信息读取：GetAdaptersAddresses（iphlpapi.dll）+ ctypes。

这个模块只读，不修改网络配置。所有结构体都按 Windows SDK 的定义手工声明，
没有 pywin32 / WMI / 第三方包。
"""
from __future__ import annotations

import ctypes
import ipaddress
import winreg
from ctypes import wintypes
from dataclasses import dataclass, field

from .win32 import iphlpapi  # type: ignore[attr-defined]

AF_INET = 2
GAA_FLAG_SKIP_ANYCAST = 0x0002
GAA_FLAG_SKIP_MULTICAST = 0x0004
GAA_FLAG_INCLUDE_PREFIX = 0x0010
GAA_FLAG_INCLUDE_GATEWAYS = 0x0080
ERROR_BUFFER_OVERFLOW = 111

IF_TYPE_ETHERNET_CSMACD = 6
IF_TYPE_IEEE80211 = 71
IF_OPER_STATUS_UP = 1

IP_ADAPTER_DHCP_ENABLED = 0x00000004
IP_ADAPTER_IPV4_ENABLED = 0x00000080


class SOCKADDR(ctypes.Structure):
    _fields_ = [
        ("sa_family", wintypes.USHORT),
        ("sa_data", ctypes.c_ubyte * 14),
    ]


class SOCKADDR_IN(ctypes.Structure):
    _fields_ = [
        ("sin_family", wintypes.USHORT),
        ("sin_port", wintypes.USHORT),
        ("sin_addr", ctypes.c_ubyte * 4),
        ("sin_zero", ctypes.c_ubyte * 8),
    ]


class SOCKET_ADDRESS(ctypes.Structure):
    _fields_ = [
        ("lpSockaddr", ctypes.POINTER(SOCKADDR)),
        ("iSockaddrLength", ctypes.c_int),
    ]


class IP_ADAPTER_UNICAST_ADDRESS(ctypes.Structure):
    pass


class IP_ADAPTER_DNS_SERVER_ADDRESS(ctypes.Structure):
    pass


class IP_ADAPTER_PREFIX(ctypes.Structure):
    pass


IP_ADAPTER_UNICAST_ADDRESS._fields_ = [
    ("Length", wintypes.ULONG),
    ("Flags", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)),
    ("Address", SOCKET_ADDRESS),
    ("PrefixOrigin", ctypes.c_int),
    ("SuffixOrigin", ctypes.c_int),
    ("DadState", ctypes.c_int),
    ("ValidLifetime", wintypes.ULONG),
    ("PreferredLifetime", wintypes.ULONG),
    ("LeaseLifetime", wintypes.ULONG),
    ("OnLinkPrefixLength", ctypes.c_ubyte),
]

IP_ADAPTER_DNS_SERVER_ADDRESS._fields_ = [
    ("Length", wintypes.ULONG),
    ("Reserved", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_DNS_SERVER_ADDRESS)),
    ("Address", SOCKET_ADDRESS),
]

IP_ADAPTER_PREFIX._fields_ = [
    ("Length", wintypes.ULONG),
    ("Flags", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_PREFIX)),
    ("Address", SOCKET_ADDRESS),
    ("PrefixLength", wintypes.ULONG),
]


class IP_ADAPTER_ADDRESSES(ctypes.Structure):
    pass


IP_ADAPTER_ADDRESSES._fields_ = [
    ("Length", wintypes.ULONG),
    ("IfIndex", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_ADDRESSES)),
    ("AdapterName", ctypes.c_char_p),
    ("FirstUnicastAddress", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)),
    ("FirstAnycastAddress", ctypes.POINTER(IP_ADAPTER_DNS_SERVER_ADDRESS)),
    ("FirstMulticastAddress", ctypes.POINTER(IP_ADAPTER_DNS_SERVER_ADDRESS)),
    ("FirstDnsServerAddress", ctypes.POINTER(IP_ADAPTER_DNS_SERVER_ADDRESS)),
    ("DnsSuffix", wintypes.LPWSTR),
    ("Description", wintypes.LPWSTR),
    ("FriendlyName", wintypes.LPWSTR),
    ("PhysicalAddress", ctypes.c_ubyte * 8),
    ("PhysicalAddressLength", wintypes.ULONG),
    ("Flags", wintypes.ULONG),
    ("Mtu", wintypes.ULONG),
    ("IfType", wintypes.ULONG),
    ("OperStatus", ctypes.c_int),
    ("Ipv6IfIndex", wintypes.ULONG),
    ("ZoneIndices", wintypes.ULONG * 16),
    ("FirstPrefix", ctypes.POINTER(IP_ADAPTER_PREFIX)),
    ("TransmitLinkSpeed", ctypes.c_ulonglong),
    ("ReceiveLinkSpeed", ctypes.c_ulonglong),
    ("FirstWinsServerAddress", ctypes.POINTER(IP_ADAPTER_DNS_SERVER_ADDRESS)),
    ("FirstGatewayAddress", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)),
    ("Ipv4Metric", wintypes.ULONG),
    ("Ipv6Metric", wintypes.ULONG),
    ("Luid", ctypes.c_ulonglong),
    ("Dhcpv4Server", SOCKET_ADDRESS),
    ("CompartmentId", wintypes.ULONG),
    ("NetworkGuid", ctypes.c_ubyte * 16),
    ("ConnectionType", ctypes.c_int),
    ("TunnelType", ctypes.c_int),
    ("Dhcpv6Server", SOCKET_ADDRESS),
    ("Dhcpv6ClientDuid", ctypes.c_ubyte * 130),
    ("Dhcpv6ClientDuidLength", wintypes.ULONG),
    ("Dhcpv6Iaid", wintypes.ULONG),
]

iphlpapi.GetAdaptersAddresses.restype = wintypes.ULONG
iphlpapi.GetAdaptersAddresses.argtypes = [
    wintypes.ULONG,
    wintypes.ULONG,
    ctypes.c_void_p,
    ctypes.POINTER(IP_ADAPTER_ADDRESSES),
    ctypes.POINTER(wintypes.ULONG),
]

_VIRTUAL_HINTS = (
    "wi-fi direct",
    "wifi direct",
    "virtual",
    "virtualbox",
    "vmware",
    "hyper-v",
    "loopback",
    "bluetooth",
    "tap-",
    "tap ",
    "tun ",
    "vpn",
    "wireguard",
    "npcap",
    "wan miniport",
    "ras async",
    "teredo",
    "isatap",
)


@dataclass
class WlanSignal:
    quality: int
    ssid: str = ""
    source: str = "WLAN API"


@dataclass
class Adapter:
    if_index: int
    guid: str
    name: str
    description: str
    mac: str
    if_type: int
    oper_status: int
    dhcp: bool
    ipv4_enabled: bool
    ipv4: str = ""
    mask: str = ""
    prefix_length: int = 0
    gateway: str = ""
    dns: tuple[str, ...] = field(default_factory=tuple)
    link_speed_bps: int = 0
    dns_static: bool = False
    signal: WlanSignal | None = None

    @property
    def is_up(self) -> bool:
        return self.oper_status == IF_OPER_STATUS_UP

    @property
    def is_wifi(self) -> bool:
        return self.if_type == IF_TYPE_IEEE80211

    @property
    def is_ethernet(self) -> bool:
        return self.if_type == IF_TYPE_ETHERNET_CSMACD

    @property
    def is_virtual(self) -> bool:
        text = f"{self.name} {self.description}".lower()
        return any(hint in text for hint in _VIRTUAL_HINTS)

    @property
    def is_configurable(self) -> bool:
        return (
            self.if_type in (IF_TYPE_ETHERNET_CSMACD, IF_TYPE_IEEE80211)
            and not self.is_virtual
            and self.ipv4_enabled
        )

    @property
    def type_label(self) -> str:
        if self.is_wifi:
            return "无线"
        if self.is_ethernet:
            return "以太网"
        return "其他"

    @property
    def status_label(self) -> str:
        if self.is_up:
            return "已连接"
        return "未连接"

    @property
    def display_name(self) -> str:
        if self.description and self.description != self.name:
            return f"{self.name} · {self.description}"
        return self.name

    @property
    def dns1(self) -> str:
        return self.dns[0] if len(self.dns) > 0 else ""

    @property
    def dns2(self) -> str:
        return self.dns[1] if len(self.dns) > 1 else ""

    def current_summary(self) -> str:
        if not self.is_up:
            return "网卡未连接"
        mode = "自动获取（DHCP）" if self.dhcp else "静态 IP"
        ip = self.ipv4 or "未分配 IPv4"
        return f"{mode} · {ip}"


def _sockaddr_ipv4(addr: SOCKET_ADDRESS) -> str:
    try:
        ptr = addr.lpSockaddr
        if not ptr or ptr.contents.sa_family != AF_INET:
            return ""
        sin = ctypes.cast(ptr, ctypes.POINTER(SOCKADDR_IN)).contents
        return ".".join(str(int(b)) for b in sin.sin_addr)
    except Exception:
        return ""


def prefix_to_mask(prefix: int) -> str:
    try:
        return str(ipaddress.IPv4Network(f"0.0.0.0/{max(0, min(32, int(prefix)))}").netmask)
    except Exception:
        return "255.255.255.0"


def _mac_text(raw: bytes) -> str:
    return "-".join(f"{b:02X}" for b in raw)


def _dns_static(guid: str) -> bool:
    """静态 DNS 会写入接口注册表 NameServer；DHCP DNS 在 DhcpNameServer。"""
    if not guid:
        return False
    key_path = (
        r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces" + "\\" + guid
    )
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            key_path,
            0,
            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
        ) as key:
            value, _ = winreg.QueryValueEx(key, "NameServer")
            return bool(str(value).strip())
    except OSError:
        return False


def _parse_adapters(buf) -> list[Adapter]:
    result: list[Adapter] = []
    head = ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_ADDRESSES))
    node = head
    while node:
        item = node.contents
        dns: list[str] = []
        dns_ptr = item.FirstDnsServerAddress
        while dns_ptr:
            address = _sockaddr_ipv4(dns_ptr.contents.Address)
            if address and address not in dns:
                dns.append(address)
            dns_ptr = dns_ptr.contents.Next

        best_ip = ""
        best_prefix = 0
        unicast = item.FirstUnicastAddress
        while unicast:
            address = _sockaddr_ipv4(unicast.contents.Address)
            if address:
                if not best_ip or (best_ip.startswith("169.254.") and not address.startswith("169.254.")):
                    best_ip = address
                    best_prefix = int(unicast.contents.OnLinkPrefixLength)
            unicast = unicast.contents.Next

        gateway = ""
        gateway_ptr = item.FirstGatewayAddress
        while gateway_ptr:
            address = _sockaddr_ipv4(gateway_ptr.contents.Address)
            if address:
                gateway = address
                break
            gateway_ptr = gateway_ptr.contents.Next

        guid = ""
        try:
            if item.AdapterName:
                guid = item.AdapterName.decode("ascii", "replace")
        except Exception:
            pass
        name = item.FriendlyName or ""
        description = item.Description or name
        result.append(
            Adapter(
                if_index=int(item.IfIndex),
                guid=guid,
                name=name,
                description=description,
                mac=_mac_text(bytes(item.PhysicalAddress[: item.PhysicalAddressLength])),
                if_type=int(item.IfType),
                oper_status=int(item.OperStatus),
                dhcp=bool(item.Flags & IP_ADAPTER_DHCP_ENABLED),
                ipv4_enabled=bool(item.Flags & IP_ADAPTER_IPV4_ENABLED),
                ipv4=best_ip,
                mask=prefix_to_mask(best_prefix) if best_ip else "",
                prefix_length=best_prefix,
                gateway=gateway,
                dns=tuple(dns),
                link_speed_bps=int(item.TransmitLinkSpeed or 0),
                dns_static=_dns_static(guid),
            )
        )
        node = item.Next
    return result


def enumerate_adapters() -> list[Adapter]:
    """枚举所有启用 IPv4 的网卡（只读，不触发任何配置写入）。"""
    flags = (
        GAA_FLAG_INCLUDE_PREFIX
        | GAA_FLAG_INCLUDE_GATEWAYS
        | GAA_FLAG_SKIP_ANYCAST
        | GAA_FLAG_SKIP_MULTICAST
    )
    size = wintypes.ULONG(15_000)
    buf = None
    for _ in range(6):
        buf = ctypes.create_string_buffer(size.value)
        ret = iphlpapi.GetAdaptersAddresses(
            AF_INET,
            flags,
            None,
            ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_ADDRESSES)),
            ctypes.byref(size),
        )
        if ret == 0:
            break
        if ret != ERROR_BUFFER_OVERFLOW:
            raise OSError(ret, f"GetAdaptersAddresses 失败（{ret}）")
    else:
        raise OSError("GetAdaptersAddresses 缓冲区不足")
    return _parse_adapters(buf)


def configurable_adapters(adapters: list[Adapter] | None = None) -> list[Adapter]:
    items = list(adapters if adapters is not None else enumerate_adapters())
    physical = [a for a in items if a.is_configurable]
    if not physical:
        physical = [
            a
            for a in items
            if a.if_type != 24 and a.ipv4_enabled and not a.description.lower().startswith("software loopback")
        ]
    physical.sort(key=lambda a: (not a.is_up, 0 if a.is_wifi else 1, a.name.lower()))
    return physical


def find_adapter(if_index: int, adapters: list[Adapter] | None = None) -> Adapter | None:
    for adapter in adapters if adapters is not None else enumerate_adapters():
        if adapter.if_index == int(if_index):
            return adapter
    return None


def find_by_guid(guid: str, adapters: list[Adapter] | None = None) -> Adapter | None:
    wanted = (guid or "").strip().lower()
    if not wanted:
        return None
    for adapter in adapters if adapters is not None else enumerate_adapters():
        if adapter.guid.lower() == wanted:
            return adapter
    return None


def canonical_ipv4(value: str) -> str:
    try:
        return str(ipaddress.IPv4Address((value or "").strip()))
    except Exception:
        return (value or "").strip()


def canonical_mask(value: str) -> str:
    try:
        return str(ipaddress.IPv4Network(f"0.0.0.0/{value.strip()}").netmask)
    except Exception:
        return (value or "").strip()


def profile_matches(adapter: Adapter, profile) -> bool:
    """比较 Windows 当前 IPv4 配置与方案（名称不参与比较）。"""
    if adapter.dhcp:
        return False
    return (
        canonical_ipv4(adapter.ipv4) == canonical_ipv4(profile.ip)
        and canonical_mask(adapter.mask) == canonical_mask(profile.mask)
        and canonical_ipv4(adapter.gateway) == canonical_ipv4(profile.gateway)
        and canonical_ipv4(adapter.dns1) == canonical_ipv4(profile.dns1)
        and canonical_ipv4(adapter.dns2) == canonical_ipv4(profile.dns2 or "")
    )


def detect_profile(adapter: Adapter | None, profiles) -> str | None:
    if adapter is None or adapter.dhcp:
        return None
    for profile in profiles:
        if profile_matches(adapter, profile):
            return profile.id
    return None


def format_config(adapter: Adapter | None) -> str:
    if adapter is None:
        return "未选择网卡"
    if not adapter.is_up:
        return "未连接"
    if adapter.dhcp:
        return f"自动获取（DHCP） · {adapter.ipv4 or '等待地址'}"
    return (
        f"静态 · {adapter.ipv4 or '无 IP'} / {adapter.mask or '—'}"
        f" · 网关 {adapter.gateway or '—'} · DNS {adapter.dns1 or '—'}"
        + (f", {adapter.dns2}" if adapter.dns2 else "")
    )
