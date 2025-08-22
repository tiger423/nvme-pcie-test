#!/usr/bin/env python3
"""
Enterprise NVMe PCIe Gen5 SSD QA Test Framework (Config-driven)
Python 3.12 + Ubuntu 24.04

Features:
- Multi-controller & multi-namespace detection
- Parallel namespace testing
- Multiple fio workloads in parallel per namespace
- SMART monitoring and trend charts
- FIO performance trend charts
- Combined Temp vs IOPS vs Latency per workload
- JSON + HTML self-contained reports
- YAML/JSON configuration file support

CLI:
  python nvme_qa.py --config config.yaml
  python nvme_qa.py --config config.json
  python nvme_qa.py  (uses built-in defaults)
"""

from __future__ import annotations
import os, json, subprocess, time, io, base64, argparse, re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# Matplotlib (required)
import matplotlib.pyplot as plt

# Optional YAML (install pyyaml)
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
    "smart": {
        "duration": 20,         # seconds
        "interval": 5           # seconds
    },
    "fio": {
        "runtime": 20,          # seconds
        "iodepth": 4,
        "bs": "4k",
        "ioengine": "io_uring",
        "workloads": ["randread", "randwrite", "read", "write", "randrw"]
    },
    "controllers": {
        "include_regex": ".*",  # test all controllers by default
        "exclude_regex": ""     # exclude none
    },
    "namespaces": {
        "include_regex": ".*",  # test all namespaces by default
        "exclude_regex": ""     # exclude none
    }
}


# ============================
# Utils
# ============================
def run_cmd(cmd: str) -> str:
    """Run a shell command and return stdout (or prefixed error string)."""
    try:
        # Python 3.12 good practice: capture_output=True + text=True + check=True
        result = subprocess.run(cmd, shell=True, text=True,
                                capture_output=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def b64_plot(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def save_json(data: dict, filepath: str) -> None:
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_config(path: str | None) -> Dict[str, Any]:
    if not path:
        return DEFAULT_CFG.copy()
    p = Path(path)
    if not p.exists():
        print(f"[WARN] Config file not found: {path}. Using defaults.")
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

    # Deep merge defaults <- user
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
    filt = re_filter(paths, cfg["controllers"]["include_regex"], cfg["controllers"]["exclude_regex"])
    return filt


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
    namespaces = re_filter(namespaces, cfg["namespaces"]["include_regex"], cfg["namespaces"]["exclude_regex"])
    return namespaces


def get_device_info(dev: str) -> Dict[str, Any]:
    return {
        "device": dev,
        "nvme_list": run_cmd(f"nvme list {dev}"),
        "id_ctrl": run_cmd(f"nvme id-ctrl {dev}"),
        # Note: mapping /dev/nvmeX to PCI address is environment-specific; keeping generic
        "pcie_info": run_cmd("lspci -vv | grep -A15 -i nvme")
    }


# ============================
# SMART Monitoring
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
                "time": datetime.now().strftime("%H:%M:%S"),
                "temperature": j.get("temperature", 0),
                "percentage_used": j.get("percentage_used", 0),
                "media_errors": j.get("media_errors", 0),
                "critical_warnings": j.get("critical_warning", 0),
            })
        except Exception:
            pass
        time.sleep(interval)
    return logs


# ============================
# fio
# ============================
def run_fio_test(ns: str, rw: str, runtime: int, iodepth: int, bs: str, ioengine: str) -> Dict[str, Any]:
    cmd = (
        f"fio --name=nvme_test --filename={ns} "
        f"--rw={rw} --bs={bs} --iodepth={iodepth} --runtime={runtime} "
        f"--time_based=1 --ioengine={ioengine} --output-format=json"
    )
    raw = run_cmd(cmd)
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
def plot_series(x_labels: List[str], values: List[float], title: str, ylabel: str) -> str:
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
    ax1.plot(times, temps, color="tab:red", marker="o", label="Temp")
    ax1.tick_params(axis="y", labelcolor="tab:red")
    ax1.set_xticklabels(times, rotation=45, fontsize=8)

    ax2 = ax1.twinx()
    ax2.set_ylabel("IOPS / Latency (us)", color="tab:blue")
    ax2.plot(times, fio_trends["iops"], color="tab:blue", marker="s", label="IOPS")
    if fio_trends.get("latency"):
        ax2.plot(times, fio_trends["latency"], color="tab:green", marker="^", label="Latency")
    ax2.tick_params(axis="y", labelcolor="tab:blue")
    fig.suptitle(f"Combined Timeline ({workload})")
    fig.tight_layout()
    return b64_plot(fig)


# ============================
# Workers
# ============================
def test_workload(ns: str, rw: str, fio_cfg: Dict[str, Any]) -> Dict[str, Any]:
    fio_json = run_fio_test(
        ns=ns,
        rw=rw,
        runtime=int(fio_cfg["runtime"]),
        iodepth=int(fio_cfg["iodepth"]),
        bs=str(fio_cfg["bs"]),
        ioengine=str(fio_cfg.get("ioengine", "io_uring"))
    )
    return {"workload": rw, "fio_json": fio_json, "fio_trends": extract_fio_trends(fio_json)}


def test_namespace(ns: str, smart_cfg: Dict[str, Any], fio_cfg: Dict[str, Any]) -> Dict[str, Any]:
    # SMART monitor (timeline)
    smart_logs = monitor_smart(ns, interval=int(smart_cfg["interval"]), duration=int(smart_cfg["duration"]))
    results: Dict[str, Any] = {"smart_logs": smart_logs, "workloads": {}}

    # Parallel workloads
    workloads: List[str] = list(fio_cfg.get("workloads", []))
    if not workloads:
        workloads = ["randread"]
    with ThreadPoolExecutor(max_workers=len(workloads)) as executor:
        futures = {executor.submit(test_workload, ns, rw, fio_cfg): rw for rw in workloads}
        for fut in as_completed(futures):
            rw = futures[fut]
            try:
                results["workloads"][rw] = fut.result()
            except Exception as e:
                results["workloads"][rw] = {"error": str(e)}

    return results


# ============================
# Report Generation
# ============================
def consolidate_results(controllers: List[str], cfg: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    out_dir = cfg["output_dir"]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    results: Dict[str, Any] = {}

    for dev in controllers:
        namespaces = list_nvme_namespaces(dev, cfg)
        dev_data: Dict[str, Any] = {"info": get_device_info(dev), "namespaces": {}}

        # Run all namespaces in parallel
        with ThreadPoolExecutor(max_workers=len(namespaces) or 1) as executor:
            futmap = {executor.submit(test_namespace, ns, cfg["smart"], cfg["fio"]): ns for ns in namespaces}
            for fut in as_completed(futmap):
                ns = futmap[fut]
                try:
                    dev_data["namespaces"][ns] = fut.result()
                except Exception as e:
                    dev_data["namespaces"][ns] = {"error": str(e)}

        results[dev] = dev_data

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

    for dev, data in results.items():
        html.append(f"<h2>Controller: {dev}</h2>")
        html.append("<h3>Device Info</h3><pre>{}</pre>".format(data["info"]))

        for ns, ns_data in data.get("namespaces", {}).items():
            html.append(f"<h3>Namespace: {ns}</h3>")

            # SMART
            logs = ns_data.get("smart_logs", [])
            if logs:
                html.append("<h4>SMART Trends</h4>")
                for metric, ylabel in [("temperature", "Temp (¢XC)"),
                                       ("percentage_used", "% Used"),
                                       ("media_errors", "Media Errors"),
                                       ("critical_warnings", "Critical Warnings")]:
                    b64 = plot_smart_trend(logs, metric, ylabel)
                    if b64:
                        html.append(f"<p>{metric}</p><img src='data:image/png;base64,{b64}'/>")

            # Workloads
            workloads = ns_data.get("workloads", {})
            for rw, rw_data in workloads.items():
                if "fio_trends" in rw_data:
                    html.append(f"<h4>Workload: {rw}</h4>")
                    iops = rw_data["fio_trends"].get("iops", [])
                    lat = rw_data["fio_trends"].get("latency", [])
                    if iops:
                        b64 = plot_series([], iops, "IOPS Trend", "IOPS")
                        html.append(f"<p>IOPS</p><img src='data:image/png;base64,{b64}'/>")
                    if lat:
                        b64 = plot_series([], lat, "Latency Trend", "Latency (us)")
                        html.append(f"<p>Latency</p><img src='data:image/png;base64,{b64}'/>")
                    combined = plot_combined_timeline(logs, rw_data["fio_trends"], rw)
                    if combined:
                        html.append(f"<h4>Combined Timeline ({rw})</h4>")
                        html.append(f"<img src='data:image/png;base64,{combined}'/>")

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

    # Discover controllers and apply regex filters
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
