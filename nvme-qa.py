
#!/usr/bin/env python3
"""
Enterprise NVMe PCIe Gen5 SSD QA Test Framework (Config-driven)
Python 3.12 + Ubuntu 24.04

Fixes in this version:
- Robust "Device Info" collection per controller:
  * Maps controller -> PCI BDF via /sys/class/nvme/<ctrl>/device
  * Reads current/max PCIe link speed/width from sysfs (if present)
  * Adds lspci -s <BDF> -vv block (scoped to the exact device)
  * Uses nvme id-ctrl -o json and nvme list-subsys <ctrl>
  * HTML now JSON-dumps (escaped) so the section never appears empty
- Plot fixes:
  * No ticklabel warning (set ticks before labels)
  * FIO series resampled to SMART timeline to avoid length mismatch
- Keeps: explicit device selection, fio_on_fs, sanitize/format/WP, mkfs/mount,
  SMART, power FID=2, sensors, turbostat, telemetry-log, --sudo auto-elevate
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
    "output_dir": "./logs",
    "smart": {"duration": 20, "interval": 5},
    "fio": {
        "runtime": 20, "iodepth": 4, "bs": "4k",
        "ioengine": "io_uring",
        "workloads": ["randread", "randwrite", "read", "write", "randrw"]
    },
    "controllers": {
        "explicit": [],                 # e.g. ["/dev/nvme0", "/dev/nvme1"]
        "include_regex": r".*",
        "exclude_regex": r""
    },
    "namespaces": {
        "explicit": [],                 # e.g. ["/dev/nvme0n1", "/dev/nvme1n1"]
        "include_regex": r".*",
        "exclude_regex": r""
    },
    "format": {"enabled": False, "lbaf": 0, "ses": 0, "wait_after": 5},
    "sanitize": {"enabled": False, "action": "none", "ause": True, "owpass": 1, "interval": 5, "timeout": 1800},
    "write_protect": {"enabled": False, "value": 1},
    "filesystem": {
        "create": False,
        "type": "ext4",
        "mkfs_options": "-F",
        "mount": False,
        "mount_base": "/mnt/nvmeqa",
        "mount_options": "defaults,noatime",
        "fio_on_fs": False,
        "fio_file_size": "8G",
        "fio_file_prefix": "fio_nvmeqa"
    },
    "telemetry": {"sensors_interval": 2, "turbostat_interval": 2, "nvme_telemetry": True, "power_interval": 2}
}

# ============================
# Utils
# ============================
def cmd_exists(name: str) -> bool:
    return subprocess.call(f"command -v {shlex.quote(name)} >/dev/null 2>&1", shell=True) == 0

def run_cmd(cmd: str, require_root: bool = False) -> str:
    try:
        if require_root and os.geteuid() != 0:
            cmd = f"sudo -n {cmd}"
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"

def read_sysfs(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None

def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def time_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")

def b64_plot(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def save_json(data: dict, filepath: str) -> None:
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def load_config(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return DEFAULT_CFG.copy()
    p = Path(path)
    if not p.exists():
        print(f"[WARN] Config not found: {path}. Using defaults.")
        return DEFAULT_CFG.copy()
    try:
        if p.suffix.lower() in (".yml", ".yaml"):
            if not HAVE_YAML:
                print("[WARN] pyyaml not installed; cannot parse YAML. Using defaults.")
                return DEFAULT_CFG.copy()
            with open(p, "r", encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
        else:
            with open(p, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
    except Exception as e:
        print(f"[WARN] Failed to parse config: {e}. Using defaults.")
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
    out = []
    for v in values:
        if inc and not inc.search(v):
            continue
        if exc and exc.search(v):
            continue
        out.append(v)
    return out

# ============================
# Discovery
# ============================
def list_all_namespaces() -> List[str]:
    raw = run_cmd("nvme list -o json")
    ns_paths: List[str] = []
    try:
        devices = json.loads(raw).get("Devices", [])
        for d in devices:
            dp = d.get("DevicePath")
            if isinstance(dp, str) and dp.startswith("/dev/nvme") and re.search(r"n\d+$", dp):
                ns_paths.append(dp)
    except Exception:
        pass
    return ns_paths

def controller_from_ns(ns: str) -> str:
    return re.sub(r"n\d+$", "", ns)

def list_nvme_controllers(cfg: Dict[str, Any]) -> List[str]:
    explicit = [c for c in cfg["controllers"].get("explicit", []) if isinstance(c, str)]
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
    return re_filter(ctrls, cfg["controllers"]["include_regex"], cfg["controllers"]["exclude_regex"])

def list_nvme_namespaces(ctrl: str, cfg: Dict[str, Any]) -> List[str]:
    explicit_ns = [n for n in cfg["namespaces"].get("explicit", []) if isinstance(n, str)]
    if explicit_ns:
        sel = [n for n in explicit_ns if controller_from_ns(n) == ctrl]
        return re_filter(sel, cfg["namespaces"]["include_regex"], cfg["namespaces"]["exclude_regex"])
    all_ns = list_all_namespaces()
    sel = [ns for ns in all_ns if controller_from_ns(ns) == ctrl]
    return re_filter(sel, cfg["namespaces"]["include_regex"], cfg["namespaces"]["exclude_regex"])

def get_pci_bdf_for_ctrl(ctrl: str) -> Optional[str]:
    # /sys/class/nvme/nvmeX/device -> .../0000:BB:DD.F
    name = os.path.basename(ctrl)  # nvmeX
    link = os.path.realpath(f"/sys/class/nvme/{name}/device")
    if not link or not os.path.exists(link):
        return None
    bdf = os.path.basename(link)
    return bdf if re.match(r"^[0-9a-fA-F]{4}:\d{2}:\d{2}\.\d$", bdf) else None

def get_device_info(ctrl: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {"controller": ctrl}
    bdf = get_pci_bdf_for_ctrl(ctrl)
    info["pci_bdf"] = bdf or "unknown"

    # sysfs PCIe attributes (if exposed)
    if bdf:
        base = f"/sys/bus/pci/devices/{bdf}"
        info["pcie_sysfs"] = {
            "current_link_speed": read_sysfs(f"{base}/current_link_speed"),
            "current_link_width": read_sysfs(f"{base}/current_link_width"),
            "max_link_speed": read_sysfs(f"{base}/max_link_speed"),
            "max_link_width": read_sysfs(f"{base}/max_link_width"),
        }
        info["lspci_vv"] = run_cmd(f"lspci -s {bdf} -vv")

    # Controller identification & topology
    info["nvme_id_ctrl_json"] = run_cmd(f"nvme id-ctrl -o json {ctrl}")
    info["nvme_list_subsys"] = run_cmd(f"nvme list-subsys {ctrl}")
    # For convenience, include a filtered 'nvme list -o json' (may be broad on some nvme-cli versions)
    info["nvme_list_json"] = run_cmd(f"nvme list -o json")

    return info

# ============================
# Provisioning Hooks
# ============================
def nsid_from_path(ns: str) -> Optional[int]:
    m = re.search(r"n(\d+)$", ns)
    return int(m.group(1)) if m else None

def format_namespace(ns: str, lbaf: int, ses: int, wait_after: int = 5) -> str:
    out = run_cmd(f"nvme format {ns} --lbaf={lbaf} --ses={ses}", require_root=True)
    if out.startswith("Error:"):
        nsid = nsid_from_path(ns)
        ctrl = controller_from_ns(ns)
        if nsid is not None:
            out2 = run_cmd(f"nvme format {ctrl} -n {nsid} --lbaf={lbaf} --ses={ses}", require_root=True)
            out += f"\nFallback(ctrl): {out2}"
    if wait_after > 0:
        time.sleep(wait_after)
    return out

def sanitize_controller(ctrl: str, action: str, ause: bool, owpass: int, interval: int, timeout: int) -> str:
    if action == "none":
        return "sanitize: skipped"
    sanact_map = {"block": 1, "overwrite": 2, "crypto": 3}
    code = sanact_map.get(action, 0)
    if code == 0:
        return f"sanitize: invalid action '{action}'"
    args = [f"nvme sanitize {ctrl} --sanact={code}"]
    if ause: args.append("--ause=1")
    if action == "overwrite": args.append(f"--owpass={owpass}")
    out = run_cmd(" ".join(args), require_root=True)
    start = time.time()
    while time.time() - start < timeout:
        status = run_cmd(f"nvme get-log {ctrl} --log-id=0x81 --log-len=512", require_root=True)
        if "Error:" in status:
            time.sleep(interval)
            break
        time.sleep(interval)
    return out

def set_namespace_write_protect(ns: str, value: int) -> str:
    nsid = nsid_from_path(ns)
    ctrl = controller_from_ns(ns)
    if nsid is None:
        return "write-protect: cannot parse NSID"
    return run_cmd(f"nvme set-feature {ctrl} -n {nsid} -f 0x82 -v {value}", require_root=True)

def create_filesystem(ns: str, fs_type: str, mkfs_options: str) -> str:
    return run_cmd(f"mkfs.{shlex.quote(fs_type)} {mkfs_options} {shlex.quote(ns)}", require_root=True)

def mount_namespace(ns: str, mount_base: str, mount_options: str) -> Tuple[str, str]:
    mp = os.path.join(mount_base, os.path.basename(ns))
    Path(mp).mkdir(parents=True, exist_ok=True)
    out = run_cmd(f"mount -o {shlex.quote(mount_options)} {shlex.quote(ns)} {shlex.quote(mp)}", require_root=True)
    return mp, out

def unmount_path(mountpoint: str) -> str:
    return run_cmd(f"umount {shlex.quote(mountpoint)}", require_root=True)

# ============================
# SMART & Power Monitoring
# ============================
def get_nvme_health(ns: str) -> str:
    return run_cmd(f"nvme smart-log -o json {ns}")

def monitor_smart(ns: str, interval: int, duration: int) -> List[Dict[str, Any]]:
    logs: List[Dict[str, Any]] = []
    start = time.time()
    while time.time() - start < duration:
        try:
            raw = get_nvme_health(ns)
            j = json.loads(raw)
            logs.append({
                "time": time_hms(),
                "temperature": j.get("temperature", 0),
                "percentage_used": j.get("percentage_used", 0),
                "media_errors": j.get("media_errors", 0),
                "critical_warnings": j.get("critical_warning", 0),
            })
        except Exception:
            pass
        time.sleep(interval)
    return logs

def parse_power_value(txt: str) -> Optional[int]:
    m = re.search(r"Current value:\s*(0x[0-9A-Fa-f]+|\d+)", txt)
    if not m: return None
    token = m.group(1)
    try:
        return int(token, 0)
    except Exception:
        return None

def get_power_state_value(ctrl: str) -> Dict[str, Any]:
    out = run_cmd(f"nvme get-feature {ctrl} -f 2 -H", require_root=True)
    if out.startswith("Error:"):
        return {"error": out}
    val = parse_power_value(out)
    return {"value": val, "raw": out}

def power_monitor(ctrl: str, interval: int, duration: int) -> List[Dict[str, Any]]:
    series: List[Dict[str, Any]] = []
    start = time.time()
    while time.time() - start < duration:
        rec = get_power_state_value(ctrl)
        rec["time"] = time_hms()
        series.append(rec)
        time.sleep(interval)
    return series

# ============================
# Telemetry helpers
# ============================
def sensors_once() -> Any:
    if not cmd_exists("sensors"):
        return "Error: sensors not found (install lm-sensors)"
    return run_cmd("sensors -j")

def sensors_monitor(interval: int, duration: int) -> List[Any]:
    out: List[Any] = []
    start = time.time()
    while time.time() - start < duration:
        out.append(sensors_once())
        time.sleep(interval)
    return out

def turbostat_run(duration: int, interval: int) -> str:
    if not cmd_exists("turbostat"):
        return "Error: turbostat not found (install linux-tools-common and linux-tools-$(uname -r))"
    iters = max(1, math.ceil(duration / max(1, interval)))
    cmd = f"turbostat --quiet --interval {interval} --num_iterations {iters} --Summary"
    return run_cmd(cmd, require_root=True)

def nvme_telemetry_log(ctrl: str) -> str:
    return run_cmd(f"nvme telemetry-log {ctrl} -o json", require_root=True)

# ============================
# fio
# ============================
def run_fio_test(target: str, rw: str, runtime: int, iodepth: int, bs: str,
                 ioengine: str, on_fs: bool = False, file_size: Optional[str] = None) -> Dict[str, Any]:
    base = (
        f"fio --name=nvme_test --filename={shlex.quote(target)} "
        f"--rw={rw} --bs={bs} --iodepth={iodepth} --runtime={runtime} "
        f"--time_based=1 --ioengine={ioengine} --output-format=json"
    )
    if on_fs and file_size:
        base += f" --size={file_size}"
    raw = run_cmd(base)
    try:
        return json.loads(raw)
    except Exception:
        return {"error": raw}

def extract_fio_trends(fio_json: Dict[str, Any]) -> Dict[str, List[float]]:
    trends = {"iops": [], "latency": []}
    jobs = fio_json.get("jobs", [])
    for job in jobs:
        read_iops = job.get("read", {}).get("iops", 0)
        write_iops = job.get("write", {}).get("iops", 0)
        trends["iops"].append(read_iops or write_iops)
        read_lat = job.get("read", {}).get("clat_ns", {}).get("mean", 0) / 1000.0
        write_lat = job.get("write", {}).get("clat_ns", {}).get("mean", 0) / 1000.0
        trends["latency"].append(read_lat or write_lat)
    return trends

# ============================
# Plotting (fixed)
# ============================
def plot_series(values: List[float], title: str, ylabel: str) -> str:
    if not values:
        return ""
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.plot(range(1, len(values) + 1), values, marker="o")
    ax.set_title(title)
    ax.set_xlabel("Interval")
    ax.set_ylabel(ylabel)
    ax.grid(True)
    fig.tight_layout()
    return b64_plot(fig)

def plot_smart_trend(logs: List[Dict[str, Any]], metric: str, ylabel: str) -> str:
    if not logs:
        return ""
    times = [e["time"] for e in logs]
    vals = [e.get(metric, 0) for e in logs]
    fig, ax = plt.subplots(figsize=(6, 3))
    x = list(range(len(times)))
    ax.plot(x, vals, marker="o")
    ax.set_title(f"{metric.replace('_',' ').title()} Trend")
    ax.set_ylabel(ylabel)
    ax.set_xlabel("Time")
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
    mapped = []
    for i in range(target_len):
        src = round(i * (n - 1) / (target_len - 1))
        mapped.append(values[src])
    return mapped

def plot_combined_timeline(smart_logs: List[Dict[str, Any]], fio_trends: Dict[str, List[float]], workload: str) -> str:
    if not smart_logs:
        return ""
    times = [e["time"] for e in smart_logs]
    temps = [e.get("temperature", 0) for e in smart_logs]
    x = list(range(len(times)))

    iops_series = _resample_to_len(fio_trends.get("iops", []), len(times))
    lat_series  = _resample_to_len(fio_trends.get("latency", []), len(times)) if fio_trends.get("latency") else []

    fig, ax1 = plt.subplots(figsize=(7, 4))
    ax1.set_xlabel("Time")
    ax1.set_ylabel("Temperature (¢XC)", color="tab:red")
    ax1.plot(x, temps, marker="o")
    ax1.tick_params(axis="y", labelcolor="tab:red")
    ax1.set_xticks(x)
    ax1.set_xticklabels(times, rotation=45, fontsize=8)

    ax2 = ax1.twinx()
    ax2.set_ylabel("IOPS / Latency (us)", color="tab:blue")
    if any(iops_series):
        ax2.plot(x, iops_series, marker="s")
    if lat_series and any(lat_series):
        ax2.plot(x, lat_series, marker="^")
    ax2.tick_params(axis="y", labelcolor="tab:blue")

    fig.suptitle(f"Combined Timeline ({workload})")
    fig.tight_layout()
    return b64_plot(fig)

# ============================
# Workers (per workload / namespace)
# ============================
def test_workload(ns: str, rw: str, fio_cfg: Dict[str, Any], tel_cfg: Dict[str, Any],
                  ctrl: str, fio_target: Optional[str] = None, on_fs: bool = False) -> Dict[str, Any]:
    runtime = int(fio_cfg["runtime"])
    with ThreadPoolExecutor(max_workers=4) as ex:
        fut_sensors = ex.submit(sensors_monitor, int(tel_cfg["sensors_interval"]), runtime)
        fut_turbo   = ex.submit(turbostat_run, runtime, int(tel_cfg["turbostat_interval"]))
        fut_power   = ex.submit(power_monitor, ctrl, int(tel_cfg.get("power_interval", 2)), runtime)
        fut_fio     = ex.submit(
            run_fio_test,
            fio_target if fio_target else ns,
            rw,
            runtime,
            int(fio_cfg["iodepth"]),
            str(fio_cfg["bs"]),
            str(fio_cfg.get("ioengine", "io_uring")),
            on_fs,
            str(fio_cfg.get("file_size")) if on_fs else None
        )
        fio_json = fut_fio.result()
        sensors_seq = fut_sensors.result()
        turbostat_txt = fut_turbo.result()
        power_seq = fut_power.result()

    return {
        "workload": rw,
        "using_fs": on_fs,
        "fio_target": fio_target if on_fs else ns,
        "fio_json": fio_json,
        "fio_trends": extract_fio_trends(fio_json),
        "telemetry": {
            "sensors_series": sensors_seq,
            "turbostat": turbostat_txt,
            "power_states": power_seq
        }
    }

def test_namespace(ns: str, cfg: Dict[str, Any], mountpoint: Optional[str] = None) -> Dict[str, Any]:
    smart_cfg = cfg["smart"]
    fio_cfg   = cfg["fio"].copy()
    tel_cfg   = cfg["telemetry"]
    fs_cfg    = cfg["filesystem"]
    ctrl      = controller_from_ns(ns)

    fio_on_fs = bool(fs_cfg.get("fio_on_fs", False)) and bool(mountpoint)
    if fio_on_fs:
        fio_cfg["file_size"] = fs_cfg.get("fio_file_size", "8G")

    smart_logs = monitor_smart(ns, interval=int(smart_cfg["interval"]), duration=int(smart_cfg["duration"]))

    workloads: List[str] = list(cfg["fio"].get("workloads", [])) or ["randread"]
    fio_targets: Dict[str, Optional[str]] = {}
    if fio_on_fs and mountpoint:
        Path(mountpoint).mkdir(parents=True, exist_ok=True)
        for rw in workloads:
            fname = f"{fs_cfg.get('fio_file_prefix','fio_nvmeqa')}_{rw}.dat"
            fio_targets[rw] = os.path.join(mountpoint, fname)
    else:
        for rw in workloads:
            fio_targets[rw] = None  # raw namespace

    results: Dict[str, Any] = {"smart_logs": smart_logs, "workloads": {}}
    with ThreadPoolExecutor(max_workers=len(workloads)) as executor:
        futures = {
            executor.submit(
                test_workload, ns, rw, fio_cfg, tel_cfg, ctrl,
                fio_target=fio_targets[rw],
                on_fs=fio_on_fs and fio_targets[rw] is not None
            ): rw for rw in workloads
        }
        for future in as_completed(futures):
            rw = futures[future]
            try:
                results["workloads"][rw] = future.result()
            except Exception as e:
                results["workloads"][rw] = {"error": str(e)}
    return results

# ============================
# Pipeline per controller
# ============================
def maybe_provision_namespace(ns: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"namespace": ns, "actions": {}}
    if cfg["write_protect"]["enabled"]:
        out["actions"]["write_protect"] = set_namespace_write_protect(ns, int(cfg["write_protect"]["value"]))
    if cfg["format"]["enabled"]:
        out["actions"]["format"] = format_namespace(ns, int(cfg["format"]["lbaf"]), int(cfg["format"]["ses"]), int(cfg["format"]["wait_after"]))
    mount_info = None
    if cfg["filesystem"]["create"]:
        fs_t = str(cfg["filesystem"]["type"])
        mkfs_opt = str(cfg["filesystem"]["mkfs_options"])
        out["actions"]["mkfs"] = create_filesystem(ns, fs_t, mkfs_opt)
        if cfg["filesystem"]["mount"]:
            mount_base = str(cfg["filesystem"]["mount_base"])
            mnt_opts   = str(cfg["filesystem"]["mount_options"])
            mp, mout = mount_namespace(ns, mount_base, mnt_opts)
            mount_info = {"mountpoint": mp, "output": mout}
            out["actions"]["mount"] = mount_info
    if mount_info:
        out["mountpoint"] = mount_info.get("mountpoint")
    return out

def maybe_unmount_namespace(ns: str, cfg: Dict[str, Any], provision_result: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    mount_info = provision_result.get("actions", {}).get("mount")
    if mount_info and cfg["filesystem"]["mount"]:
        mp = mount_info.get("mountpoint")
        if mp:
            out["umount"] = unmount_path(mp)
    return out

# ============================
# Report Generation
# ============================
def consolidate_results(controllers: List[str], cfg: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    out_dir = cfg["output_dir"]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    results: Dict[str, Any] = {}

    for ctrl in controllers:
        if cfg["sanitize"]["enabled"]:
            results.setdefault(ctrl, {})["sanitize"] = sanitize_controller(
                ctrl=ctrl,
                action=str(cfg["sanitize"]["action"]),
                ause=bool(cfg["sanitize"]["ause"]),
                owpass=int(cfg["sanitize"]["owpass"]),
                interval=int(cfg["sanitize"]["interval"]),
                timeout=int(cfg["sanitize"]["timeout"])
            )

        namespaces = list_nvme_namespaces(ctrl, cfg)
        dev_data: Dict[str, Any] = results.setdefault(ctrl, {})
        dev_data["info"] = get_device_info(ctrl)
        dev_data["namespaces"] = {}

        prov_map: Dict[str, Dict[str, Any]] = {}
        for ns in namespaces:
            prov_map[ns] = maybe_provision_namespace(ns, cfg)

        with ThreadPoolExecutor(max_workers=len(namespaces) or 1) as executor:
            futmap = {
                executor.submit(test_namespace, ns, cfg, mountpoint=prov_map.get(ns, {}).get("mountpoint")): ns
                for ns in namespaces
            }
            for fut in as_completed(futmap):
                ns = futmap[fut]
                try:
                    dev_data["namespaces"][ns] = {"provision": prov_map.get(ns, {}), "results": fut.result()}
                except Exception as e:
                    dev_data["namespaces"][ns] = {"provision": prov_map.get(ns, {}), "results": {"error": str(e)}}

        for ns in namespaces:
            dev_data["namespaces"][ns]["post"] = maybe_unmount_namespace(ns, cfg, dev_data["namespaces"][ns]["provision"])

        if cfg["telemetry"].get("nvme_telemetry", True):
            dev_data["nvme_telemetry_log"] = nvme_telemetry_log(ctrl)

    json_path = os.path.join(out_dir, f"ssd_report_{timestamp()}.json")
    save_json(results, json_path)
    return json_path, results

def generate_html_report(results: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    out_dir = cfg["output_dir"]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    html_file = os.path.join(out_dir, f"ssd_report_{timestamp()}.html")

    html = [
        "<html><head><meta charset='utf-8'><title>NVMe SSD Report</title></head><body>",
        "<h1>Enterprise NVMe PCIe Gen5 SSD Report</h1><hr>"
    ]

    for ctrl, data in results.items():
        html.append(f"<h2>Controller: {ctrl}</h2>")
        if "sanitize" in data:
            html.append(f"<details><summary>Sanitize Result</summary><pre>{html_escape(str(data['sanitize']))}</pre></details>")

        # Device Info (JSON pretty + escaped)
        info_pretty = html_escape(json.dumps(data.get("info", {}), indent=2))
        html.append("<h3>Device Info</h3><pre>{}</pre>".format(info_pretty))

        if data.get("nvme_telemetry_log"):
            html.append("<details><summary>NVMe Telemetry Log (controller)</summary>")
            html.append(f"<pre>{html_escape(str(data['nvme_telemetry_log']))}</pre></details>")

        for ns, ns_obj in data.get("namespaces", {}).items():
            html.append(f"<h3>Namespace: {ns}</h3>")

            prov = ns_obj.get("provision", {}).get("actions", {})
            if prov:
                html.append("<details><summary>Provisioning</summary><pre>")
                html.append(html_escape(json.dumps(prov, indent=2)))
                html.append("</pre></details>")

            res = ns_obj.get("results", {})
            logs = res.get("smart_logs", [])
            if logs:
                html.append("<h4>SMART Trends</h4>")
                for metric, ylabel in [("temperature", "Temp (¢XC)"),
                                       ("percentage_used", "% Used"),
                                       ("media_errors", "Media Errors"),
                                       ("critical_warnings", "Critical Warnings")]:
                    b64 = plot_smart_trend(logs, metric, ylabel)
                    if b64:
                        html.append(f"<p>{metric}</p><img src='data:image/png;base64,{b64}'/>")

            workloads = res.get("workloads", {})
            for rw, wdata in workloads.items():
                if "fio_trends" in wdata:
                    html.append(f"<h4>Workload: {rw} {'(fio_on_fs)' if wdata.get('using_fs') else '(raw)'} </h4>")
                    html.append(f"<p><b>Target:</b> {html_escape(str(wdata.get('fio_target')))}</p>")
                    iops = wdata["fio_trends"].get("iops", [])
                    lat = wdata["fio_trends"].get("latency", [])
                    if iops:
                        b64 = plot_series(iops, "IOPS Trend", "IOPS")
                        html.append(f"<p>IOPS</p><img src='data:image/png;base64,{b64}'/>")
                    if lat:
                        b64 = plot_series(lat, "Latency Trend", "Latency (us)")
                        html.append(f"<p>Latency</p><img src='data:image/png;base64,{b64}'/>")
                    combined = plot_combined_timeline(logs, wdata["fio_trends"], rw)
                    if combined:
                        html.append(f"<h4>Combined Timeline ({rw})</h4>")
                        html.append(f"<img src='data:image/png;base64,{combined}'/>")

                    tele = wdata.get("telemetry", {})
                    if tele:
                        html.append("<details><summary>Per-Workload Telemetry</summary><pre>")
                        html.append(html_escape(json.dumps({
                            "power_states": tele.get("power_states", []),
                            "sensors_series": tele.get("sensors_series", "n/a"),
                            "turbostat": (tele.get("turbostat", "n/a") or "")[:100000]
                        }, indent=2)))
                        html.append("</pre></details>")

            post = ns_obj.get("post", {})
            if post:
                html.append("<details><summary>Post Actions</summary><pre>")
                html.append(html_escape(json.dumps(post, indent=2)))
                html.append("</pre></details>")

        html.append("<hr>")

    html.append("</body></html>")
    with open(html_file, "w", encoding="utf-8") as f:
        f.write("".join(html))
    return html_file

# ============================
# CLI
# ============================
def main():
    ap = argparse.ArgumentParser(description="Enterprise NVMe PCIe Gen5 SSD QA Framework (config-driven)")
    ap.add_argument("--config", "-c", type=str, default=None, help="Path to YAML/JSON config")
    ap.add_argument("--sudo", action="store_true", help="Re-exec this script under sudo if not already root")
    args = ap.parse_args()

    if args.sudo and os.geteuid() != 0:
        os.execvp("sudo", ["sudo", "-E", sys.executable, __file__] + (["--config", args.config] if args.config else []))

    cfg = load_config(args.config)

    controllers = list_nvme_controllers(cfg)
    if not controllers:
        print("[ERROR] No NVMe controllers detected (or filtered out).")
        return
    print(f"[INFO] Controllers under test: {controllers}")

    json_path, results = consolidate_results(controllers, cfg)
    print(f"[OK] JSON saved: {json_path}")

    html_path = generate_html_report(results, cfg)
    print(f"[OK] HTML saved: {html_path}")

if __name__ == "__main__":
    main()
