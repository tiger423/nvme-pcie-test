#!/usr/bin/env python3
r"""
Enterprise NVMe PCIe Gen5 SSD QA Test Framework (Config-driven)
Python 3.12 + Ubuntu 24.04

Highlights / Fixes:
- Robust "Device Info" (PCI BDF via sysfs/uevent/udevadm, hex bus/device supported).
- Safe `nvme list-subsys` wrapper (normalizes /dev path, fallbacks).
- Global command-output sanitizer (removes ANSI, applies backspaces, normalizes CR).
- Correct discovery (no bogus '/dev/nvme1n1n1').
- Explicit controller/namespace selection in config.
- fio_on_fs mode (file-based workloads on created/mounted FS).
- Power state sampling via 'nvme get-feature -f 2' during workloads.
- SMART trends, sensors, turbostat, nvme telemetry-log.
- JSON + HTML reports (embedded plots; escaped blocks).
- Plot fixes (ticks/ticklabels + series resampling).
- Privileged commands auto sudo-able; --sudo re-exec option.
- All string literals are raw (r"...") or raw+formatted (fr"...").

Usage:
  python3 nvme_qa.py --config config.yaml
  python3 nvme_qa.py --config config.yaml --sudo
  sudo -E python3 nvme_qa.py --config config.yaml
"""

from __future__ import annotations
import os, sys, json, subprocess, time, io, base64, argparse, re, math, shlex
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import matplotlib.pyplot as plt

# Optional YAML
try:
    import yaml  # type: ignore
    HAVE_YAML = True
except Exception:
    HAVE_YAML = False

# ============================
# Defaults (used if no config)
# ============================
DEFAULT_CFG: Dict[str, Any] = {
    r"output_dir": r"./logs",
    r"smart": {r"duration": 20, r"interval": 5},
    r"fio": {
        r"runtime": 20,
        r"iodepth": 4,
        r"bs": r"4k",
        r"ioengine": r"io_uring",
        r"workloads": [r"randread", r"randwrite", r"read", r"write", r"randrw"],
    },
    r"controllers": {
        r"explicit": [],                 # e.g. ["/dev/nvme0", "/dev/nvme1"]
        r"include_regex": r".*",
        r"exclude_regex": r"",
    },
    r"namespaces": {
        r"explicit": [],                 # e.g. ["/dev/nvme0n1", "/dev/nvme1n1"]
        r"include_regex": r".*",
        r"exclude_regex": r"",
    },
    r"format": {r"enabled": False, r"lbaf": 0, r"ses": 0, r"wait_after": 5},
    r"sanitize": {
        r"enabled": False,
        r"action": r"none",
        r"ause": True,
        r"owpass": 1,
        r"interval": 5,
        r"timeout": 1800,
    },
    r"write_protect": {r"enabled": False, r"value": 1},
    r"filesystem": {
        r"create": False,
        r"type": r"ext4",
        r"mkfs_options": r"-F",
        r"mount": False,
        r"mount_base": r"/mnt/nvmeqa",
        r"mount_options": r"defaults,noatime",
        r"fio_on_fs": False,
        r"fio_file_size": r"8G",
        r"fio_file_prefix": r"fio_nvmeqa",
    },
    r"telemetry": {
        r"sensors_interval": 2,
        r"turbostat_interval": 2,
        r"nvme_telemetry": True,
        r"power_interval": 2,
    },
}

# ============================
# Output Sanitizer (ANSI/CR/backspaces)
# ============================
import re as _re

_ANSI_RE = _re.compile(r"\x1B\[[0-9;?]*[ -/]*[@-~]")  # CSI sequences

def _strip_ansi(s: str) -> str:
    if not isinstance(s, str):
        return s
    return _ANSI_RE.sub(r"", s)

def _normalize_cr(s: str) -> str:
    r"""
    For lines with carriage returns (progress redraw), keep only the final segment.
    Example: "Alloc 10%\rAlloc 20%\rdone\n" -> "done\n"
    """
    if not s or r"\r" not in s and "\r" not in s:
        return s
    fixed_lines: List[str] = []
    for line in s.splitlines(keepends=False):
        if "\r" in line:
            fixed_lines.append(line.split("\r")[-1])
        else:
            fixed_lines.append(line)
    return "\n".join(fixed_lines)

def _apply_backspaces(s: str) -> str:
    r"""
    Apply terminal-style backspaces robustly:
    - For every '\b', delete the previous kept character if any.
    - Works even if there are trailing '\b' without a prior char.
    """
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
    return s.replace("\x00", r"").strip()

# ============================
# Utils
# ============================
def cmd_exists(name: str) -> bool:
    return subprocess.call(fr"command -v {shlex.quote(name)} >/dev/null 2>&1", shell=True) == 0

def run_cmd(cmd: str, require_root: bool = False) -> str:
    r"""Run a shell command and return stdout (or prefixed error)."""
    try:
        if require_root and os.geteuid() != 0:
            cmd = fr"sudo -n {cmd}"
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True, check=True)
        return sanitize_cmd_output(result.stdout)
    except subprocess.CalledProcessError as e:
        return fr"Error: {sanitize_cmd_output(e.stderr)}"

def read_sysfs(path: str) -> Optional[str]:
    try:
        with open(path, r"r", encoding=r"utf-8") as f:
            return f.read().strip()
    except Exception:
        return None

def timestamp() -> str:
    return datetime.now().strftime(r"%Y-%m-%d_%H-%M-%S")

def time_hms() -> str:
    return datetime.now().strftime(r"%H:%M:%S")

def b64_plot(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format=r"png")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode(r"utf-8")

def save_json(data: dict, filepath: str) -> None:
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, r"w", encoding=r"utf-8") as f:
        json.dump(data, f, indent=2)

def html_escape(s: str) -> str:
    return s.replace(r"&", r"&amp;").replace(r"<", r"&lt;").replace(r">", r"&gt;")

# ============================
# Discovery
# ============================
def load_config(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return DEFAULT_CFG.copy()
    p = Path(path)
    if not p.exists():
        print(fr"[WARN] Config not found: {path}. Using defaults.")
        return DEFAULT_CFG.copy()
    try:
        if p.suffix.lower() in (r".yml", r".yaml"):
            if not HAVE_YAML:
                print(r"[WARN] pyyaml not installed; cannot parse YAML. Using defaults.")
                return DEFAULT_CFG.copy()
            with open(p, r"r", encoding=r"utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
        else:
            with open(p, r"r", encoding=r"utf-8") as f:
                user_cfg = json.load(f)
    except Exception as e:
        print(fr"[WARN] Failed to parse config: {e}. Using defaults.")
        return DEFAULT_CFG.copy()

    cfg = DEFAULT_CFG.copy()

    def deep_merge(a, b):
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                deep_merge(a[k], v)
            else:
                a[k] = v

    deep_merge(cfg, user_cfg)
    return cfg

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

def list_all_namespaces() -> List[str]:
    raw = run_cmd(r"nvme list -o json")
    ns_paths: List[str] = []
    try:
        devices = json.loads(raw).get(r"Devices", [])
        for d in devices:
            dp = d.get(r"DevicePath")
            if isinstance(dp, str) and dp.startswith(r"/dev/nvme") and re.search(r"n\d+$", dp):
                ns_paths.append(dp)
    except Exception:
        pass
    return ns_paths

def controller_from_ns(ns: str) -> str:
    return re.sub(r"n\d+$", r"", ns)

def list_nvme_controllers(cfg: Dict[str, Any]) -> List[str]:
    explicit = [c for c in cfg[r"controllers"].get(r"explicit", []) if isinstance(c, str)]
    if explicit:
        ctrls: List[str] = []
        for c in explicit:
            ctrls.append(controller_from_ns(c) if re.search(r"n\d+$", c) else c)
        seen, result = set(), []
        for c in ctrls:
            if c not in seen:
                result.append(c); seen.add(c)
        return result
    ns_paths = list_all_namespaces()
    ctrls = sorted({controller_from_ns(ns) for ns in ns_paths})
    return re_filter(ctrls, cfg[r"controllers"][r"include_regex"], cfg[r"controllers"][r"exclude_regex"])

def list_nvme_namespaces(ctrl: str, cfg: Dict[str, Any]) -> List[str]:
    explicit_ns = [n for n in cfg[r"namespaces"].get(r"explicit", []) if isinstance(n, str)]
    if explicit_ns:
        sel = [n for n in explicit_ns if controller_from_ns(n) == ctrl]
        return re_filter(sel, cfg[r"namespaces"][r"include_regex"], cfg[r"namespaces"][r"exclude_regex"])
    all_ns = list_all_namespaces()
    sel = [ns for ns in all_ns if controller_from_ns(ns) == ctrl]
    return re_filter(sel, cfg[r"namespaces"][r"include_regex"], cfg[r"namespaces"][r"exclude_regex"])

# ============================
# Device Info (PCI BDF + nvme-cli wrappers)
# ============================
def _normalize_ctrl_path(ctrl: str) -> str:
    r"""Ensure controller path looks like '/dev/nvmeX'."""
    base = os.path.basename(ctrl)
    if not base.startswith(r"nvme"):
        return ctrl
    return ctrl if ctrl.startswith(r"/dev/") else fr"/dev/{base}"

def _safe_nvme_list_subsys(ctrl: str) -> str:
    r"""
    Robust wrapper for 'nvme list-subsys' that tolerates strict device-name checks.

    Strategy:
      1) Try: nvme list-subsys -o json <ctrl>
      2) If error, ensure '/dev/' prefix and retry.
      3) If error, list all: nvme list-subsys -o json
      4) If still error, last resort: nvme list-subsys (text)
    """
    out = run_cmd(fr"nvme list-subsys -o json {ctrl}")
    if not out.startswith(r"Error:"):
        return out
    ctrl_norm = _normalize_ctrl_path(ctrl)
    if ctrl_norm != ctrl:
        out2 = run_cmd(fr"nvme list-subsys -o json {ctrl_norm}")
        if not out2.startswith(r"Error:"):
            return out2
    out3 = run_cmd(r"nvme list-subsys -o json")
    if not out3.startswith(r"Error:"):
        return out3
    return run_cmd(r"nvme list-subsys")

def get_pci_bdf_for_ctrl(ctrl: str) -> Optional[str]:
    r"""
    Resolve the PCI BDF for a controller like '/dev/nvme1'.

    Accepts hex for bus/device (e.g., '0000:da:00.0').

    Strategy:
      1) Start from /sys/class/nvme/<name>/device (realpath) and climb up.
      2) While climbing, look for a BDF-like basename, or parse PCI_SLOT_NAME from 'uevent'.
      3) If needed, use 'udevadm info --query=path --name=<ctrl>' to get the sysfs node and repeat.
      4) Fallback: scan the absolute path string for a BDF substring.
    """
    name = os.path.basename(ctrl)  # e.g. 'nvme1'
    bdf_re_full = re.compile(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]")
    bdf_re_base = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$")

    def find_in_path(p: str) -> Optional[str]:
        m = bdf_re_full.search(p)
        return m.group(0) if m else None

    def climb_for_bdf(start_path: str) -> Optional[str]:
        p = os.path.realpath(start_path)
        # Quick scan of the entire absolute path
        bdf = find_in_path(p)
        if bdf:
            return bdf
        # Walk up several levels to catch BDF as a directory basename
        for _ in range(12):
            base = os.path.basename(p)
            if bdf_re_base.fullmatch(base):
                return base
            uevent = read_sysfs(os.path.join(p, r"uevent"))
            if uevent:
                m = re.search(r"PCI_SLOT_NAME=([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7])", uevent)
                if m:
                    return m.group(1)
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
        return None

    sys_node = fr"/sys/class/nvme/{name}/device"
    if os.path.exists(sys_node):
        bdf = climb_for_bdf(sys_node)
        if bdf:
            return bdf

    if cmd_exists(r"udevadm"):
        rel = run_cmd(fr"udevadm info --query=path --name={shlex.quote(ctrl)}")
        if rel and not rel.startswith(r"Error:"):
            abs_path = os.path.realpath(os.path.join(r"/sys", rel.lstrip(r"/")))
            bdf = climb_for_bdf(abs_path)
            if bdf:
                return bdf
            bdf = find_in_path(abs_path)
            if bdf:
                return bdf

    return None

def get_device_info(ctrl: str) -> Dict[str, Any]:
    ctrl_norm = _normalize_ctrl_path(ctrl)
    info: Dict[str, Any] = {r"controller": ctrl_norm}
    bdf = get_pci_bdf_for_ctrl(ctrl_norm)
    info[r"pci_bdf"] = bdf or r"unknown"

    if bdf:
        base = fr"/sys/bus/pci/devices/{bdf}"
        info[r"pcie_sysfs"] = {
            r"current_link_speed": read_sysfs(fr"{base}/current_link_speed"),
            r"current_link_width": read_sysfs(fr"{base}/current_link_width"),
            r"max_link_speed": read_sysfs(fr"{base}/max_link_speed"),
            r"max_link_width": read_sysfs(fr"{base}/max_link_width"),
        }
        info[r"lspci_vv"] = run_cmd(fr"lspci -s {bdf} -vv")
    else:
        name = os.path.basename(ctrl_norm)
        info[r"debug_sysfs_exists"] = {
            r"/sys/class/nvme/<name>": os.path.exists(fr"/sys/class/nvme/{name}"),
            r"/sys/class/nvme/<name>/device": os.path.exists(fr"/sys/class/nvme/{name}/device"),
        }
        if cmd_exists(r"udevadm"):
            info[r"debug_udevadm_path"] = run_cmd(fr"udevadm info --query=path --name={shlex.quote(ctrl_norm)}")

    info[r"nvme_id_ctrl_json"] = run_cmd(fr"nvme id-ctrl -o json {ctrl_norm}")
    info[r"nvme_list_subsys"] = _safe_nvme_list_subsys(ctrl_norm)
    info[r"nvme_list_json"] = run_cmd(r"nvme list -o json")
    return info

# ============================
# Provisioning Hooks
# ============================
def nsid_from_path(ns: str) -> Optional[int]:
    m = re.search(r"n(\d+)$", ns)
    return int(m.group(1)) if m else None

def format_namespace(ns: str, lbaf: int, ses: int, wait_after: int = 5) -> str:
    out = run_cmd(fr"nvme format {ns} --lbaf={lbaf} --ses={ses}", require_root=True)
    if out.startswith(r"Error:"):
        nsid = nsid_from_path(ns)
        ctrl = controller_from_ns(ns)
        if nsid is not None:
            out2 = run_cmd(fr"nvme format {ctrl} -n {nsid} --lbaf={lbaf} --ses={ses}", require_root=True)
            out += fr"\nFallback(ctrl): {out2}"
    if wait_after > 0:
        time.sleep(wait_after)
    return out

def sanitize_controller(ctrl: str, action: str, ause: bool, owpass: int, interval: int, timeout: int) -> str:
    if action == r"none":
        return r"sanitize: skipped"
    sanact_map = {r"block": 1, r"overwrite": 2, r"crypto": 3}
    code = sanact_map.get(action, 0)
    if code == 0:
        return fr"sanitize: invalid action '{action}'"
    args = [fr"nvme sanitize {ctrl} --sanact={code}"]
    if ause:
        args.append(r"--ause=1")
    if action == r"overwrite":
        args.append(fr"--owpass={owpass}")
    out = run_cmd(r" ".join(args), require_root=True)
    start = time.time()
    while time.time() - start < timeout:
        status = run_cmd(fr"nvme get-log {ctrl} --log-id=0x81 --log-len=512", require_root=True)
        if r"Error:" in status:
            time.sleep(interval)
            break
        time.sleep(interval)
    return out

def set_namespace_write_protect(ns: str, value: int) -> str:
    nsid = nsid_from_path(ns)
    ctrl = controller_from_ns(ns)
    if nsid is None:
        return r"write-protect: cannot parse NSID"
    return run_cmd(fr"nvme set-feature {ctrl} -n {nsid} -f 0x82 -v {value}", require_root=True)

def create_filesystem(ns: str, fs_type: str, mkfs_options: str) -> str:
    return run_cmd(fr"mkfs.{shlex.quote(fs_type)} {mkfs_options} {shlex.quote(ns)}", require_root=True)

def mount_namespace(ns: str, mount_base: str, mount_options: str) -> Tuple[str, str]:
    mp = os.path.join(mount_base, os.path.basename(ns))
    Path(mp).mkdir(parents=True, exist_ok=True)
    out = run_cmd(fr"mount -o {shlex.quote(mount_options)} {shlex.quote(ns)} {shlex.quote(mp)}", require_root=True)
    return mp, out

def unmount_path(mountpoint: str) -> str:
    return run_cmd(fr"umount {shlex.quote(mountpoint)}", require_root=True)

# ============================
# SMART & Power Monitoring
# ============================
def get_nvme_health(ns: str) -> str:
    return run_cmd(fr"nvme smart-log -o json {ns}")

def monitor_smart(ns: str, interval: int, duration: int) -> List[Dict[str, Any]]:
    logs: List[Dict[str, Any]] = []
    start = time.time()
    while time.time() - start < duration:
        try:
            raw = get_nvme_health(ns)
            j = json.loads(raw)
            logs.append({
                r"time": time_hms(),
                r"temperature": j.get(r"temperature", 0),
                r"percentage_used": j.get(r"percentage_used", 0),
                r"media_errors": j.get(r"media_errors", 0),
                r"critical_warnings": j.get(r"critical_warning", 0),
            })
        except Exception:
            pass
        time.sleep(interval)
    return logs

def parse_power_value(txt: str) -> Optional[int]:
    m = re.search(r"Current value:\s*(0x[0-9A-Fa-f]+|\d+)", txt)
    if not m:
        return None
    token = m.group(1)
    try:
        return int(token, 0)
    except Exception:
        return None

def get_power_state_value(ctrl: str) -> Dict[str, Any]:
    out = run_cmd(fr"nvme get-feature {ctrl} -f 2 -H", require_root=True)
    if out.startswith(r"Error:"):
        return {r"error": out}
    val = parse_power_value(out)
    return {r"value": val, r"raw": out}

def power_monitor(ctrl: str, interval: int, duration: int) -> List[Dict[str, Any]]:
    series: List[Dict[str, Any]] = []
    start = time.time()
    while time.time() - start < duration:
        rec = get_power_state_value(ctrl)
        rec[r"time"] = time_hms()
        series.append(rec)
        time.sleep(interval)
    return series

# ============================
# Telemetry helpers
# ============================
def sensors_once() -> Any:
    if not cmd_exists(r"sensors"):
        return r"Error: sensors not found (install lm-sensors)"
    return run_cmd(r"sensors -j")

def sensors_monitor(interval: int, duration: int) -> List[Any]:
    out: List[Any] = []
    start = time.time()
    while time.time() - start < duration:
        out.append(sensors_once())
        time.sleep(interval)
    return out

def turbostat_run(duration: int, interval: int) -> str:
    if not cmd_exists(r"turbostat"):
        return r"Error: turbostat not found (install linux-tools-common and linux-tools-$(uname -r))"
    iters = max(1, math.ceil(duration / max(1, interval)))
    cmd = fr"turbostat --quiet --interval {interval} --num_iterations {iters} --Summary"
    return run_cmd(cmd, require_root=True)

def nvme_telemetry_log(ctrl: str) -> str:
    return run_cmd(fr"nvme telemetry-log {ctrl} -o json", require_root=True)

# ============================
# fio
# ============================
def run_fio_test(target: str, rw: str, runtime: int, iodepth: int, bs: str,
                 ioengine: str, on_fs: bool = False, file_size: Optional[str] = None) -> Dict[str, Any]:
    base = (
        fr"fio --name=nvme_test --filename={shlex.quote(target)} "
        fr"--rw={rw} --bs={bs} --iodepth={iodepth} --runtime={runtime} "
        fr"--time_based=1 --ioengine={ioengine} --output-format=json"
    )
    if on_fs and file_size:
        base += fr" --size={file_size}"
    raw = run_cmd(base)
    try:
        return json.loads(raw)
    except Exception:
        return {r"error": raw}

def extract_fio_trends(fio_json: Dict[str, Any]) -> Dict[str, List[float]]:
    trends = {r"iops": [], r"latency": []}
    jobs = fio_json.get(r"jobs", [])
    for job in jobs:
        read_iops = job.get(r"read", {}).get(r"iops", 0)
        write_iops = job.get(r"write", {}).get(r"iops", 0)
        trends[r"iops"].append(read_iops or write_iops)
        read_lat = job.get(r"read", {}).get(r"clat_ns", {}).get(r"mean", 0) / 1000.0
        write_lat = job.get(r"write", {}).get(r"clat_ns", {}).get(r"mean", 0) / 1000.0
        trends[r"latency"].append(read_lat or write_lat)
    return trends

# ============================
# Plotting (fixed)
# ============================
def plot_series(values: List[float], title: str, ylabel: str) -> str:
    if not values:
        return r""
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.plot(range(1, len(values) + 1), values, marker=r"o")
    ax.set_title(title)
    ax.set_xlabel(r"Interval")
    ax.set_ylabel(ylabel)
    ax.grid(True)
    fig.tight_layout()
    return b64_plot(fig)

def plot_smart_trend(logs: List[Dict[str, Any]], metric: str, ylabel: str) -> str:
    if not logs:
        return r""
    times = [e[r"time"] for e in logs]
    vals = [e.get(metric, 0) for e in logs]
    fig, ax = plt.subplots(figsize=(6, 3))
    x = list(range(len(times)))
    ax.plot(x, vals, marker=r"o")
    ax.set_title(fr"{metric.replace('_',' ').title()} Trend")
    ax.set_ylabel(ylabel)
    ax.set_xlabel(r"Time")
    ax.set_xticks(x)
    ax.set_xticklabels(times, rotation=45, fontsize=8)
    ax.grid(True)
    fig.tight_layout()
    return b64_plot(fig)

def _resample_to_len(values: List[float], target_len: int) -> List[float]:
    if target_len <= 0:
        return []
    if not values:
        return [0.0] * target_len
    n = len(values)
    if n == target_len:
        return values
    if target_len == 1:
        return [values[0]]
    mapped: List[float] = []
    for i in range(target_len):
        src = round(i * (n - 1) / (target_len - 1))
        mapped.append(values[src])
    return mapped

def plot_combined_timeline(smart_logs: List[Dict[str, Any]], fio_trends: Dict[str, List[float]], workload: str) -> str:
    if not smart_logs:
        return r""
    times = [e[r"time"] for e in smart_logs]
    temps = [e.get(r"temperature", 0) for e in smart_logs]
    x = list(range(len(times)))

    iops_series = _resample_to_len(fio_trends.get(r"iops", []), len(times))
    lat_series  = _resample_to_len(fio_trends.get(r"latency", []), len(times)) if fio_trends.get(r"latency") else []

    fig, ax1 = plt.subplots(figsize=(7, 4))
    ax1.set_xlabel(r"Time")
    ax1.set_ylabel(r"Temperature (°C)", color=r"tab:red")
    ax1.plot(x, temps, marker=r"o")
    ax1.tick_params(axis=r"y", labelcolor=r"tab:red")
    ax1.set_xticks(x)
    ax1.set_xticklabels(times, rotation=45, fontsize=8)

    ax2 = ax1.twinx()
    ax2.set_ylabel(r"IOPS / Latency (us)", color=r"tab:blue")
    if any(iops_series):
        ax2.plot(x, iops_series, marker=r"s")
    if lat_series and any(lat_series):
        ax2.plot(x, lat_series, marker=r"^")
    ax2.tick_params(axis=r"y", labelcolor=r"tab:blue")

    fig.suptitle(fr"Combined Timeline ({workload})")
    fig.tight_layout()
    return b64_plot(fig)

# ============================
# Workers (per workload / namespace)
# ============================
def test_workload(ns: str, rw: str, fio_cfg: Dict[str, Any], tel_cfg: Dict[str, Any],
                  ctrl: str, fio_target: Optional[str] = None, on_fs: bool = False) -> Dict[str, Any]:
    runtime = int(fio_cfg[r"runtime"])
    with ThreadPoolExecutor(max_workers=4) as ex:
        fut_sensors = ex.submit(sensors_monitor, int(tel_cfg[r"sensors_interval"]), runtime)
        fut_turbo   = ex.submit(turbostat_run, runtime, int(tel_cfg[r"turbostat_interval"]))
        fut_power   = ex.submit(power_monitor, ctrl, int(tel_cfg.get(r"power_interval", 2)), runtime)
        fut_fio     = ex.submit(
            run_fio_test,
            fio_target if fio_target else ns,
            rw,
            runtime,
            int(fio_cfg[r"iodepth"]),
            str(fio_cfg[r"bs"]),
            str(fio_cfg.get(r"ioengine", r"io_uring")),
            on_fs,
            str(fio_cfg.get(r"file_size")) if on_fs else None,
        )
        fio_json = fut_fio.result()
        sensors_seq = fut_sensors.result()
        turbostat_txt = fut_turbo.result()
        power_seq = fut_power.result()

    return {
        r"workload": rw,
        r"using_fs": on_fs,
        r"fio_target": fio_target if on_fs else ns,
        r"fio_json": fio_json,
        r"fio_trends": extract_fio_trends(fio_json),
        r"telemetry": {
            r"sensors_series": sensors_seq,
            r"turbostat": turbostat_txt,
            r"power_states": power_seq,
        },
    }

def test_namespace(ns: str, cfg: Dict[str, Any], mountpoint: Optional[str] = None) -> Dict[str, Any]:
    smart_cfg = cfg[r"smart"]
    fio_cfg   = cfg[r"fio"].copy()
    tel_cfg   = cfg[r"telemetry"]
    fs_cfg    = cfg[r"filesystem"]
    ctrl      = controller_from_ns(ns)

    fio_on_fs = bool(fs_cfg.get(r"fio_on_fs", False)) and bool(mountpoint)
    if fio_on_fs:
        fio_cfg[r"file_size"] = fs_cfg.get(r"fio_file_size", r"8G")

    smart_logs = monitor_smart(ns, interval=int(smart_cfg[r"interval"]), duration=int(smart_cfg[r"duration"]))

    workloads: List[str] = list(cfg[r"fio"].get(r"workloads", [])) or [r"randread"]
    fio_targets: Dict[str, Optional[str]] = {}
    if fio_on_fs and mountpoint:
        Path(mountpoint).mkdir(parents=True, exist_ok=True)
        for rw in workloads:
            fname = fr"{fs_cfg.get('fio_file_prefix','fio_nvmeqa')}_{rw}.dat"
            fio_targets[rw] = os.path.join(mountpoint, fname)
    else:
        for rw in workloads:
            fio_targets[rw] = None  # raw namespace

    results: Dict[str, Any] = {r"smart_logs": smart_logs, r"workloads": {}}
    with ThreadPoolExecutor(max_workers=len(workloads)) as executor:
        futures = {
            executor.submit(
                test_workload,
                ns,
                rw,
                fio_cfg,
                tel_cfg,
                ctrl,
                fio_target=fio_targets[rw],
                on_fs=fio_on_fs and fio_targets[rw] is not None,
            ): rw
            for rw in workloads
        }
        for future in as_completed(futures):
            rw = futures[future]
            try:
                results[r"workloads"][rw] = future.result()
            except Exception as e:
                results[r"workloads"][rw] = {r"error": str(e)}
    return results

# ============================
# Pipeline per controller
# ============================
def maybe_provision_namespace(ns: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {r"namespace": ns, r"actions": {}}
    if cfg[r"write_protect"][r"enabled"]:
        out[r"actions"][r"write_protect"] = set_namespace_write_protect(ns, int(cfg[r"write_protect"][r"value"]))
    if cfg[r"format"][r"enabled"]:
        out[r"actions"][r"format"] = format_namespace(
            ns, int(cfg[r"format"][r"lbaf"]), int(cfg[r"format"][r"ses"]), int(cfg[r"format"][r"wait_after"])
        )
    mount_info = None
    if cfg[r"filesystem"][r"create"]:
        fs_t = str(cfg[r"filesystem"][r"type"])
        mkfs_opt = str(cfg[r"filesystem"][r"mkfs_options"])
        out[r"actions"][r"mkfs"] = create_filesystem(ns, fs_t, mkfs_opt)
        if cfg[r"filesystem"][r"mount"]:
            mount_base = str(cfg[r"filesystem"][r"mount_base"])
            mnt_opts   = str(cfg[r"filesystem"][r"mount_options"])
            mp, mout = mount_namespace(ns, mount_base, mnt_opts)
            mount_info = {r"mountpoint": mp, r"output": mout}
            out[r"actions"][r"mount"] = mount_info
    if mount_info:
        out[r"mountpoint"] = mount_info.get(r"mountpoint")
    return out

def maybe_unmount_namespace(ns: str, cfg: Dict[str, Any], provision_result: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    mount_info = provision_result.get(r"actions", {}).get(r"mount")
    if mount_info and cfg[r"filesystem"][r"mount"]:
        mp = mount_info.get(r"mountpoint")
        if mp:
            out[r"umount"] = unmount_path(mp)
    return out

# ============================
# Report Generation
# ============================
def consolidate_results(controllers: List[str], cfg: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    out_dir = cfg[r"output_dir"]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    results: Dict[str, Any] = {}

    for ctrl in controllers:
        if cfg[r"sanitize"][r"enabled"]:
            results.setdefault(ctrl, {})[r"sanitize"] = sanitize_controller(
                ctrl=ctrl,
                action=str(cfg[r"sanitize"][r"action"]),
                ause=bool(cfg[r"sanitize"][r"ause"]),
                owpass=int(cfg[r"sanitize"][r"owpass"]),
                interval=int(cfg[r"sanitize"][r"interval"]),
                timeout=int(cfg[r"sanitize"][r"timeout"]),
            )

        namespaces = list_nvme_namespaces(ctrl, cfg)
        dev_data: Dict[str, Any] = results.setdefault(ctrl, {})
        dev_data[r"info"] = get_device_info(ctrl)
        dev_data[r"namespaces"] = {}

        prov_map: Dict[str, Dict[str, Any]] = {}
        for ns in namespaces:
            prov_map[ns] = maybe_provision_namespace(ns, cfg)

        with ThreadPoolExecutor(max_workers=len(namespaces) or 1) as executor:
            futmap = {
                executor.submit(
                    test_namespace, ns, cfg, mountpoint=prov_map.get(ns, {}).get(r"mountpoint")
                ): ns
                for ns in namespaces
            }
            for fut in as_completed(futmap):
                ns = futmap[fut]
                try:
                    dev_data[r"namespaces"][ns] = {r"provision": prov_map.get(ns, {}), r"results": fut.result()}
                except Exception as e:
                    dev_data[r"namespaces"][ns] = {r"provision": prov_map.get(ns, {}), r"results": {r"error": str(e)}}

        for ns in namespaces:
            dev_data[r"namespaces"][ns][r"post"] = maybe_unmount_namespace(ns, cfg, dev_data[r"namespaces"][ns][r"provision"])

        if cfg[r"telemetry"].get(r"nvme_telemetry", True):
            dev_data[r"nvme_telemetry_log"] = nvme_telemetry_log(ctrl)

    json_path = os.path.join(out_dir, fr"ssd_report_{timestamp()}.json")
    save_json(results, json_path)
    return json_path, results

def generate_html_report(results: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    out_dir = cfg[r"output_dir"]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    html_file = os.path.join(out_dir, fr"ssd_report_{timestamp()}.html")

    html: List[str] = [
        r"<html><head><meta charset='utf-8'><title>NVMe SSD Report</title></head><body>",
        r"<h1>Enterprise NVMe PCIe Gen5 SSD Report</h1><hr>",
    ]

    for ctrl, data in results.items():
        html.append(fr"<h2>Controller: {ctrl}</h2>")
        if r"sanitize" in data:
            html.append(fr"<details><summary>Sanitize Result</summary><pre>{html_escape(str(data['sanitize']))}</pre></details>")

        info_pretty = html_escape(json.dumps(data.get(r"info", {}), indent=2))
        html.append(fr"<h3>Device Info</h3><pre>{info_pretty}</pre>")

        if data.get(r"nvme_telemetry_log"):
            html.append(r"<details><summary>NVMe Telemetry Log (controller)</summary>")
            html.append(fr"<pre>{html_escape(str(data['nvme_telemetry_log']))}</pre></details>")

        for ns, ns_obj in data.get(r"namespaces", {}).items():
            html.append(fr"<h3>Namespace: {ns}</h3>")

            prov = ns_obj.get(r"provision", {}).get(r"actions", {})
            if prov:
                html.append(r"<details><summary>Provisioning</summary><pre>")
                html.append(html_escape(json.dumps(prov, indent=2)))
                html.append(r"</pre></details>")

            res = ns_obj.get(r"results", {})
            logs = res.get(r"smart_logs", [])
            if logs:
                html.append(r"<h4>SMART Trends</h4>")
                for metric, ylabel in [(r"temperature", r"Temp (°C)"),
                                       (r"percentage_used", r"% Used"),
                                       (r"media_errors", r"Media Errors"),
                                       (r"critical_warnings", r"Critical Warnings")]:
                    b64 = plot_smart_trend(logs, metric, ylabel)
                    if b64:
                        html.append(fr"<p>{metric}</p><img src='data:image/png;base64,{b64}'/>")

            workloads = res.get(r"workloads", {})
            for rw, wdata in workloads.items():
                if r"fio_trends" in wdata:
                    html.append(fr"<h4>Workload: {rw} {'(fio_on_fs)' if wdata.get('using_fs') else '(raw)'} </h4>")
                    html.append(fr"<p><b>Target:</b> {html_escape(str(wdata.get('fio_target')))}</p>")
                    iops = wdata[r"fio_trends"].get(r"iops", [])
                    lat = wdata[r"fio_trends"].get(r"latency", [])
                    if iops:
                        b64 = plot_series(iops, r"IOPS Trend", r"IOPS")
                        html.append(fr"<p>IOPS</p><img src='data:image/png;base64,{b64}'/>")
                    if lat:
                        b64 = plot_series(lat, r"Latency Trend", r"Latency (us)")
                        html.append(fr"<p>Latency</p><img src='data:image/png;base64,{b64}'/>")
                    combined = plot_combined_timeline(logs, wdata[r"fio_trends"], rw)
                    if combined:
                        html.append(fr"<h4>Combined Timeline ({rw})</h4>")
                        html.append(fr"<img src='data:image/png;base64,{combined}'/>")

                    tele = wdata.get(r"telemetry", {})
                    if tele:
                        html.append(r"<details><summary>Per-Workload Telemetry</summary><pre>")
                        html.append(html_escape(json.dumps({
                            r"power_states": tele.get(r"power_states", []),
                            r"sensors_series": tele.get(r"sensors_series", r"n/a"),
                            r"turbostat": (tele.get(r"turbostat", r"n/a") or r"")[:100000],
                        }, indent=2)))
                        html.append(r"</pre></details>")

            post = ns_obj.get(r"post", {})
            if post:
                html.append(r"<details><summary>Post Actions</summary><pre>")
                html.append(html_escape(json.dumps(post, indent=2)))
                html.append(r"</pre></details>")

        html.append(r"<hr>")

    html.append(r"</body></html>")
    with open(html_file, r"w", encoding=r"utf-8") as f:
        f.write(r"".join(html))
    return html_file

# ============================
# CLI
# ============================
def main():
    ap = argparse.ArgumentParser(description=r"Enterprise NVMe PCIe Gen5 SSD QA Framework (config-driven)")
    ap.add_argument(r"--config", r"-c", type=str, default=None, help=r"Path to YAML/JSON config")
    ap.add_argument(r"--sudo", action=r"store_true", help=r"Re-exec this script under sudo if not already root")
    args = ap.parse_args()

    if args.sudo and os.geteuid() != 0:
        os.execvp(r"sudo", [r"sudo", r"-E", sys.executable, __file__] + ([r"--config", args.config] if args.config else []))

    cfg = load_config(args.config)

    controllers = list_nvme_controllers(cfg)
    if not controllers:
        print(r"[ERROR] No NVMe controllers detected (or filtered out).")
        return
    print(fr"[INFO] Controllers under test: {controllers}")

    json_path, results = consolidate_results(controllers, cfg)
    print(fr"[OK] JSON saved: {json_path}")

    html_path = generate_html_report(results, cfg)
    print(fr"[OK] HTML saved: {html_path}")

if __name__ == r"__main__":
    main()

