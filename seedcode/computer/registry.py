"""Registry driver: read anywhere, write only through explicit confirmation.

The permission layer (:mod:`seedcode.computer.permissions`) forces a per-write
user confirmation — this module only performs the operations. Uses the
standard-library ``winreg``; hive names accept the common long and short
forms (HKEY_CURRENT_USER / HKCU, ...).
"""

from __future__ import annotations

import sys

_HIVE_ALIASES = {
    "hkcu": "HKEY_CURRENT_USER",
    "hkey_current_user": "HKEY_CURRENT_USER",
    "hklm": "HKEY_LOCAL_MACHINE",
    "hkey_local_machine": "HKEY_LOCAL_MACHINE",
    "hkcr": "HKEY_CLASSES_ROOT",
    "hkey_classes_root": "HKEY_CLASSES_ROOT",
    "hku": "HKEY_USERS",
    "hkey_users": "HKEY_USERS",
    "hkcc": "HKEY_CURRENT_CONFIG",
    "hkey_current_config": "HKEY_CURRENT_CONFIG",
}

_MAX_LIST = 200


def _winreg():
    if sys.platform != "win32":
        raise RuntimeError("The registry only exists on Windows.")
    import winreg

    return winreg


def parse_key(path: str):
    """Split 'HKCU\\Software\\...' into (hive handle, subkey, display name)."""
    winreg = _winreg()
    raw = (path or "").strip().strip("\\")
    if not raw:
        raise ValueError("Registry path is required, e.g. HKCU\\Software\\MyApp.")
    hive_part, _, subkey = raw.partition("\\")
    hive_name = _HIVE_ALIASES.get(hive_part.lower())
    if hive_name is None:
        raise ValueError(
            f"Unknown registry hive '{hive_part}'. "
            "Use HKCU, HKLM, HKCR, HKU, or HKCC."
        )
    return getattr(winreg, hive_name), subkey, f"{hive_name}\\{subkey}".rstrip("\\")


def read_value(path: str, name: str) -> str:
    """Read one value ('' name means the key's default value)."""
    winreg = _winreg()
    hive, subkey, display = parse_key(path)
    with winreg.OpenKey(hive, subkey) as key:
        value, kind = winreg.QueryValueEx(key, name or "")
    return f"{display} : {name or '(default)'} = {value!r} (type {kind})"


def list_key(path: str) -> str:
    """List a key's subkeys and values."""
    winreg = _winreg()
    hive, subkey, display = parse_key(path)
    subkeys: list[str] = []
    values: list[str] = []
    with winreg.OpenKey(hive, subkey) as key:
        info = winreg.QueryInfoKey(key)
        for i in range(min(info[0], _MAX_LIST)):
            subkeys.append(winreg.EnumKey(key, i))
        for i in range(min(info[1], _MAX_LIST)):
            name, value, kind = winreg.EnumValue(key, i)
            values.append(f"{name or '(default)'} = {value!r} (type {kind})")
    lines = [f"{display}:"]
    if subkeys:
        lines.append("  subkeys: " + ", ".join(subkeys))
    if values:
        lines += [f"  {v}" for v in values]
    if not subkeys and not values:
        lines.append("  (empty)")
    return "\n".join(lines)


def write_value(path: str, name: str, value: str, value_type: str = "REG_SZ") -> str:
    """Create/overwrite a string or dword value (key is created if missing)."""
    winreg = _winreg()
    hive, subkey, display = parse_key(path)
    kind_name = value_type.strip().upper()
    if kind_name == "REG_SZ":
        kind, data = winreg.REG_SZ, str(value)
    elif kind_name == "REG_DWORD":
        kind, data = winreg.REG_DWORD, int(value)
    else:
        raise ValueError("Only REG_SZ and REG_DWORD writes are supported.")
    with winreg.CreateKey(hive, subkey) as key:
        winreg.SetValueEx(key, name or "", 0, kind, data)
    return f"Wrote {display} : {name or '(default)'} = {data!r} ({kind_name})"


def delete_value(path: str, name: str) -> str:
    """Delete one value from a key."""
    winreg = _winreg()
    hive, subkey, display = parse_key(path)
    with winreg.OpenKey(hive, subkey, 0, winreg.KEY_SET_VALUE) as key:
        winreg.DeleteValue(key, name or "")
    return f"Deleted {display} : {name or '(default)'}"
