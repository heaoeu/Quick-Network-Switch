"""WLAN API（wlanapi.dll）：读取 Wi-Fi 信号质量。

Windows 的 WlanQueryInterface 需要 WLAN 服务且调用方有足够权限；在某些
受限令牌、精简系统或策略环境下会返回 ERROR_ACCESS_DENIED。此模块在这种情况下
安静地返回空结果，界面会退回显示「链路可用」而不是伪造信号百分比。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from .netinfo import Adapter, WlanSignal
from .win32 import GUID, wlanapi  # type: ignore[attr-defined]

WLAN_INTF_OPCODE_CURRENT_CONNECTION = 7
ERROR_SUCCESS = 0


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [
        ("InterfaceGuid", GUID),
        ("strInterfaceDescription", wintypes.WCHAR * 256),
        ("isState", ctypes.c_int),
    ]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfItems", wintypes.DWORD),
        ("dwIndex", wintypes.DWORD),
        ("InterfaceInfo", WLAN_INTERFACE_INFO * 1),
    ]


class DOT11_SSID(ctypes.Structure):
    _fields_ = [
        ("uSSIDLength", wintypes.ULONG),
        ("ucSSID", ctypes.c_ubyte * 32),
    ]


class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("dot11Ssid", DOT11_SSID),
        ("dot11BssType", ctypes.c_int),
        ("dot11Bssid", ctypes.c_ubyte * 6),
        ("dot11PhyType", ctypes.c_int),
        ("uDot11PhyIndex", wintypes.ULONG),
        ("wlanSignalQuality", wintypes.ULONG),
        ("ulRxRate", wintypes.ULONG),
        ("ulTxRate", wintypes.ULONG),
    ]


class WLAN_SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("bSecurityEnabled", wintypes.BOOL),
        ("bOneXEnabled", wintypes.BOOL),
        ("dot11AuthAlgorithm", ctypes.c_int),
        ("dot11CipherAlgorithm", ctypes.c_int),
    ]


class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("isState", ctypes.c_int),
        ("wlanConnectionMode", ctypes.c_int),
        ("strProfileName", wintypes.WCHAR * 256),
        ("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES),
        ("wlanSecurityAttributes", WLAN_SECURITY_ATTRIBUTES),
    ]


wlanapi.WlanOpenHandle.restype = wintypes.DWORD
wlanapi.WlanOpenHandle.argtypes = [
    wintypes.DWORD,
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.HANDLE),
]
wlanapi.WlanEnumInterfaces.restype = wintypes.DWORD
wlanapi.WlanEnumInterfaces.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)),
]
wlanapi.WlanQueryInterface.restype = wintypes.DWORD
wlanapi.WlanQueryInterface.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(GUID),
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(wintypes.DWORD),
]
wlanapi.WlanFreeMemory.argtypes = [ctypes.c_void_p]
wlanapi.WlanCloseHandle.restype = wintypes.DWORD
wlanapi.WlanCloseHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]


def guid_to_string(guid: GUID) -> str:
    tail = "".join(f"{int(b):02X}" for b in guid.Data4)
    return f"{{{guid.Data1:08X}-{guid.Data2:04X}-{guid.Data3:04X}-{tail[:4]}-{tail[4:]}}}"


def query_signals(adapters: list[Adapter]) -> dict[int, WlanSignal]:
    """返回 {if_index: WlanSignal}；失败/无权限时返回空字典。"""
    wifi = [a for a in adapters if a.is_wifi]
    if not wifi:
        return {}
    negotiated = wintypes.DWORD()
    handle = wintypes.HANDLE()
    result = wlanapi.WlanOpenHandle(2, None, ctypes.byref(negotiated), ctypes.byref(handle))
    if result != ERROR_SUCCESS or not handle:
        return {}
    info_ptr = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
    signals: dict[int, WlanSignal] = {}
    try:
        result = wlanapi.WlanEnumInterfaces(handle, None, ctypes.byref(info_ptr))
        if result != ERROR_SUCCESS or not info_ptr:
            return {}
        by_guid = {a.guid.lower(): a for a in wifi if a.guid}
        count = int(info_ptr.contents.dwNumberOfItems)
        for index in range(count):
            info = info_ptr.contents.InterfaceInfo[index]
            adapter = by_guid.get(guid_to_string(info.InterfaceGuid).lower())
            if adapter is None:
                continue
            data = ctypes.c_void_p()
            size = wintypes.DWORD()
            ret = wlanapi.WlanQueryInterface(
                handle,
                ctypes.byref(info.InterfaceGuid),
                WLAN_INTF_OPCODE_CURRENT_CONNECTION,
                None,
                ctypes.byref(size),
                ctypes.byref(data),
                None,
            )
            if ret != ERROR_SUCCESS or not data:
                continue
            try:
                attr = ctypes.cast(data, ctypes.POINTER(WLAN_CONNECTION_ATTRIBUTES)).contents
                quality = int(attr.wlanAssociationAttributes.wlanSignalQuality)
                if not 0 <= quality <= 100:
                    continue
                ssid_len = min(32, int(attr.wlanAssociationAttributes.dot11Ssid.uSSIDLength))
                raw_ssid = bytes(attr.wlanAssociationAttributes.dot11Ssid.ucSSID[:ssid_len])
                ssid = raw_ssid.decode("utf-8", "replace").strip("\x00")
                signals[adapter.if_index] = WlanSignal(quality=quality, ssid=ssid)
            finally:
                wlanapi.WlanFreeMemory(data)
        return signals
    finally:
        if info_ptr:
            wlanapi.WlanFreeMemory(info_ptr)
        wlanapi.WlanCloseHandle(handle, None)
