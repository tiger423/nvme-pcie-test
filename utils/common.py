#!/usr/bin/env python3
"""
Common utilities extracted from nvme-qa.py for use in samples
"""

import os
import sys
import json
import subprocess
import re
import shlex
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

_ANSI_RE = re.compile(r"\x1B\[[0-9;?]*[ -/]*[@-~]")

def _strip_ansi(s: str) -> str:
    if not isinstance(s, str):
        return s
    return _ANSI_RE.sub("", s)

def _normalize_cr(s: str) -> str:
    if not s or "\r" not in s:
        return s
    fixed_lines: List[str] = []
    for line in s.splitlines(keepends=False):
        if "\r" in line:
            fixed_lines.append(line.split("\r")[-1])
        else:
            fixed_lines.append(line)
    return "\n".join(fixed_lines)

def _apply_backspaces(s: str) -> str:
    if not s or "\b" not in s:
        return s
    out_chars: List[str] = []
    for ch in s:
        if ch == "\b":
            if out_chars:
                out_chars.pop()
        else:
            out_chars.append(ch)
    return "".join(out_chars)

def sanitize_cmd_output(s: str) -> str:
    if not isinstance(s, str):
        return s
    s = _strip_ansi(s)
    s = _normalize_cr(s)
    s = _apply_backspaces(s)
    return s.replace("\x00", "").strip()

def cmd_exists(name: str) -> bool:
    return subprocess.call(f"command -v {shlex.quote(name)} >/dev/null 2>&1", shell=True) == 0

def run_cmd(cmd: str, require_root: bool = False) -> str:
    try:
        if require_root and os.geteuid() != 0:
            cmd = f"sudo -n {cmd}"
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True, check=True)
        return sanitize_cmd_output(result.stdout)
    except subprocess.CalledProcessError as e:
        return f"Error: {sanitize_cmd_output(e.stderr)}"

def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def time_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")

def nvme_list_json() -> Dict[str, Any]:
    raw = run_cmd("nvme list -o json")
    try:
        return json.loads(raw)
    except Exception:
        return {}

def list_nvme_devices_nvme_cli() -> Tuple[List[str], List[str]]:
    j = nvme_list_json()
    ctrls: set[str] = set()
    nss: List[str] = []
    for dev in j.get("Devices", []):
        dp = dev.get("DevicePath")
        if isinstance(dp, str) and dp.startswith("/dev/nvme"):
            if re.search(r"n\d+$", dp):
                nss.append(dp)
                ctrls.add(re.sub(r"n\d+$", "", dp))
            else:
                ctrls.add(dp)
    return sorted(ctrls), nss

def controller_from_ns(ns: str) -> str:
    return re.sub(r"n\d+$", "", ns)

def re_filter(values: List[str], include_regex: str, exclude_regex: str) -> List[str]:
    inc = re.compile(include_regex) if include_regex else None
    exc = re.compile(exclude_regex) if exclude_regex else None
    out: List[str] = []
    for v in values:
        if inc and not inc.search(v):
            continue
        if exc and exc.search(v):
            continue
        out.append(v)
    return out

def get_nvme_health(ns: str) -> str:
    return run_cmd(f"nvme smart-log -o json {ns}")

def check_sudo_access() -> bool:
    return os.geteuid() == 0 or subprocess.call("sudo -n true", shell=True) == 0

def print_header(title: str):
    print("=" * 60)
    print(f" {title}")
    print("=" * 60)

def print_section(title: str):
    print(f"\n--- {title} ---")

def confirm_action(message: str) -> bool:
    while True:
        response = input(f"{message} (y/N): ").strip().lower()
        if response in ['y', 'yes']:
            return True
        elif response in ['n', 'no', '']:
            return False
        else:
            print("Please enter 'y' or 'n'")
