#!/usr/bin/env python3
"""
Enterprise NVMe PCIe Gen5 SSD QA Test Framework (Config-driven)
Python 3.12 + Ubuntu 24.04

New in this version:
- fio_on_fs mode: if enabled and the namespace is mounted, run fio on a file under the mountpoint
- Power state tracking: sample NVMe Power Management (FID=2) during workloads

Other features:
- Multi-controller & multi-namespace discovery (nvme-cli JSON)
- Parallel namespace testing
- Multiple fio workloads in parallel per namespace
- SMART monitoring timelines (temperature, %used, media errors, critical warnings)
- FIO performance trends (IOPS & latency)
- Combined Temp vs IOPS vs Latency charts (per workload)
- JSON + HTML reporting (self-contained, base64 images)
- YAML/JSON configuration
- Hooks: sanitize, format, namespace write-protect, mkfs/mount provisioning
- Per-workload telemetry: `sensors -j`, `turbostat`, and optional `nvme telemetry-log` per controller
"""

from __future__ import annotations
import os, json, subprocess, time, io, base64, argparse, re, math, shlex
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
        "runtime": 20,
        "iodepth": 4,
        "bs": "4k",
        "ioengine": "io_uring",
        "workloads": ["randread", "randwrite", "read", "write", "randrw"]
    },
    "controllers": {"include_regex": ".*", "exclude_regex": ""},
    "namespaces": {"include_regex": ".*", "exclude_regex": ""},
    "format": {
        "enabled": False, "lbaf": 0, "ses": 0, "wait_after": 5
    },
    "sanitize": {
        "enabled": False, "action": "none", "ause": True,
        "owpass": 1, "interval": 5, "timeout": 1800
    },
    "write_protect": {"enabled": False, "value": 1},
    "filesystem": {
        "create": False,
        "type": "ext4",
        "mkfs_options": "-F",
        "mount": False,
        "mount_base": "/mnt/nvmeqa",
        "mount_options": "defaults,noatime",
        # NEW:
        "fio_on_fs": False,             # run fio on file under mountpoint if True
        "fio_file_size": "8G",          # fio test file size when using fio_on_fs
        "fio_file_prefix": "fio_nvmeqa" # filename prefix
    },
    "telemetry": {
        "sensors_interval": 2,
        "turbostat_interval": 2,
        "nvme_telemetry": True,
        # NEW power sampling interval (seconds)
        "power_interval": 2
    }
}


# ============================
# Utils
# ============================
def cmd_exists(name: str) -> bool:
    return subprocess.call(f"command -v {shlex.quote(name)} >/dev/null 2>&1", shell=True) == 0


def run_cmd(cmd: str, require_root: bool = False) -> str:
    """Run a shell command and return stdout (or prefixed error)."""
    try:
        if require_root and os.geteuid() != 0:
            cmd = f"sudo -n {cmd}"
        result = subprocess.run(cmd, shell=True, text=True,
                                capture_output=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"


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
def list_nvme_devices(cfg: Dict[str, Any]) -> List[str]:
    raw = run_cmd("nvme list -o json")
    try:
        devices = json.loads(raw).get("Devices", [])
        paths = [d["DevicePath"] for d in devices]
    except Exception:
        paths = []
    return re_filter(paths, cfg["controllers"]["include_regex"], cfg["controllers"]["exclude_regex"])


def list_nvme_namespaces(dev: str, cfg: Dict[str, Any]) -> List[str]:
    raw = run_cmd(f"nvme list -o json {dev}")
    namespaces: List[str] = []
    try:
        parsed = json.loads(raw)
        for d in parsed.get("Devices", []):
            for n in d.get("Namespaces", []):
                ns = n.get("NameSpace")
                if ns:
                    namespaces.append(ns)
    except Exception:
        pass
    if not namespaces:
        namespaces.append(dev + "n1")
    return re_filter(namespaces, cfg["namespaces"]["include_regex"], cfg["namespaces"]["exclude_regex"])


def get_device_info(dev: str) -> Dict[str, Any]:
    return {
        "device": dev,
        "nvme_list": run_cmd(f"nvme list {dev}"),
        "id_ctrl": run_cmd(f"nvme id-ctrl {dev}"),
        "pcie_info": run_cmd("lspci -vv | grep -A15 -i nvme")
    }


def nsid_from_path(ns: str) -> Optional[int]:
    m = re.search(r"n(\d+)$", ns)
    return int(m.group(1)) if m else None


def controller_from_ns(ns: str) -> str:
    # /dev/nvme0n1 -> /dev/nvme0
    return re.sub(r"n\d+$", "", ns)


# ============================
# Provisioning Hooks
# ============================
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
    if ause:
        args.append("--ause=1")
    if action == "overwrite":
        args.append(f"--owpass={owpass}")
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
    # Typical: "get-feature:0x02 (Power Management), Current value:00000001"
    m = re.search(r"Current value:\s*(0x[0-9A-Fa-f]+|\d+)", txt)
    if not m:
        return None
    token = m.group(1)
    try:
        return int(token, 0)
    except Exception:
        return None


def get_power_state_value(ctrl: str) -> Dict[str, Any]:
    out = run_cmd(f"nvme get-feature {ctrl} -f 2 -H")
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
# Telemetry (sensors / turbostat / nvme telemetry-log)
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
    return run_cmd(f"nvme telemetry-log {ctrl} -o json", require_root=False)


# ============================
# fio
# ============================
def run_fio_test(target: str, rw: str, runtime: int, iodepth: int, bs: str,
                 ioengine: str, on_fs: bool = False, file_size: Optional[str] = None) -> Dict[str, Any]:
    """
    target: raw namespace (e.g., /dev/nvme0n1) or a file path under a mounted filesystem
    on_fs: if True, include --size=<file_size> to bound file size (optional)
    """
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
# Plotting
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
    ax.plot(times, vals, marker="o")
    ax.set_title(f"{metric.replace('_',' ').title()} Trend")
    ax.set_ylabel(ylabel)
    ax.set_xticks(times)
    ax.set_xticklabels(times, rotation=45, fontsize=8)
    ax.grid(True)
    fig.tight_layout()
    return b64_plot(fig)


def plot_combined_timeline(smart_logs: List[Dict[str, Any]], fio_trends: Dict[str, List[float]], workload: str) -> str:
    if not smart_logs or not fio_trends.get("iops"):
        return ""
    times = [e["time"] for e in smart_logs]
    temps = [e.get("temperature", 0) for e in smart_logs]
    fig, ax1 = plt.subplots(figsize=(7, 4))
    ax1.set_xlabel("Time")
    ax1.set_ylabel("Temperature (¢XC)", color="tab:red")
    ax1.plot(times, temps, marker="o")
    ax1.tick_params(axis="y", labelcolor="tab:red")
    ax1.set_xticklabels(times, rotation=45, fontsize=8)

    ax2 = ax1.twinx()
    ax2.set_ylabel("IOPS / Latency (us)", color="tab:blue")
    ax2.plot(times, fio_trends["iops"], marker="s")
    if fio_trends.get("latency"):
        ax2.plot(times, fio_trends["latency"], marker="^")
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
    # telemetry threads in parallel with fio
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

    # align fio_on_fs config into fio_cfg for run_fio_test
    fio_on_fs = bool(fs_cfg.get("fio_on_fs", False)) and bool(mountpoint)
    if fio_on_fs:
        # set file_size for fio if provided
        fio_cfg["file_size"] = fs_cfg.get("fio_file_size", "8G")

    # SMART timeline
    smart_logs = monitor_smart(ns, interval=int(smart_cfg["interval"]), duration=int(smart_cfg["duration"]))

    # Prepare fio targets
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

    # Run all workloads in parallel
    results: Dict[str, Any] = {"smart_logs": smart_logs, "workloads": {}}
    with ThreadPoolExecutor(max_workers=len(workloads)) as executor:
        futures = {
            executor.submit(
                test_workload,
                ns, rw, fio_cfg, tel_cfg, ctrl,
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
        out["actions"]["format"] = format_namespace(
            ns, int(cfg["format"]["lbaf"]), int(cfg["format"]["ses"]), int(cfg["format"]["wait_after"])
        )

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

    # Remember mountpoint if any
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

        # Provision all namespaces first (WP/format/mkfs/mount)
        prov_map: Dict[str, Dict[str, Any]] = {}
        for ns in namespaces:
            prov_map[ns] = maybe_provision_namespace(ns, cfg)

        # Run tests in parallel across namespaces (pass mountpoint if any)
        with ThreadPoolExecutor(max_workers=len(namespaces) or 1) as executor:
            futmap = {
                executor.submit(
                    test_namespace,
                    ns,
                    cfg,
                    mountpoint=prov_map.get(ns, {}).get("mountpoint")
                ): ns for ns in namespaces
            }
            for fut in as_completed(futmap):
                ns = futmap[fut]
                try:
                    dev_data["namespaces"][ns] = {
                        "provision": prov_map.get(ns, {}),
                        "results": fut.result()
                    }
                except Exception as e:
                    dev_data["namespaces"][ns] = {
                        "provision": prov_map.get(ns, {}),
                        "results": {"error": str(e)}
                    }

        # Unmount where applicable
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
            html.append(f"<details><summary>Sanitize Result</summary><pre>{data['sanitize']}</pre></details>")
        html.append("<h3>Device Info</h3><pre>{}</pre>".format(data.get("info", {})))

        if data.get("nvme_telemetry_log"):
            html.append("<details><summary>NVMe Telemetry Log (controller)</summary>")
            html.append(f"<pre>{data['nvme_telemetry_log']}</pre></details>")

        for ns, ns_obj in data.get("namespaces", {}).items():
            html.append(f"<h3>Namespace: {ns}</h3>")

            prov = ns_obj.get("provision", {}).get("actions", {})
            if prov:
                html.append("<details><summary>Provisioning</summary><pre>")
                html.append(json.dumps(prov, indent=2))
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
                    html.append(f"<p><b>Target:</b> {wdata.get('fio_target')}</p>")
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
                        html.append(json.dumps({
                            "power_states": tele.get("power_states", []),
                            "sensors_series": tele.get("sensors_series", "n/a"),
                            "turbostat": tele.get("turbostat", "n/a")[:100000]
                        }, indent=2))
                        html.append("</pre></details>")

            post = ns_obj.get("post", {})
            if post:
                html.append("<details><summary>Post Actions</summary><pre>")
                html.append(json.dumps(post, indent=2))
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
    args = ap.parse_args()

    cfg = load_config(args.config)

    controllers = list_nvme_devices(cfg)
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
