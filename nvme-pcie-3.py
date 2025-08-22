#!/usr/bin/env python3
"""
Enterprise NVMe PCIe Gen5 SSD QA Test Framework
Python 3.12 + Ubuntu 24.04 Compatible

Features:
- Multi-namespace detection & parallel testing
- SMART monitoring with trend charts
- fio performance testing with trend charts
- Combined Temp vs IOPS vs Latency timeline
- JSON + HTML reporting
"""

import os
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
import matplotlib.pyplot as plt
import io
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================
# Utility Functions
# ============================
def run_cmd(cmd: str) -> str:
    """Run a shell command and return stdout (or error string)."""
    try:
        result = subprocess.run(
            cmd, shell=True, text=True,
            capture_output=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"


def save_json(data: dict, filepath: str) -> None:
    """Save dictionary as JSON file."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def timestamp() -> str:
    """Return formatted timestamp."""
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def b64_plot(fig) -> str:
    """Convert matplotlib figure to base64 string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ============================
# Device & Namespace Manager
# ============================
def list_nvme_devices() -> list[str]:
    """Detect NVMe controllers using nvme-cli JSON output."""
    raw = run_cmd("nvme list -o json")
    try:
        devices = json.loads(raw).get("Devices", [])
        return [d["DevicePath"] for d in devices]
    except Exception:
        return []


def list_nvme_namespaces(dev: str) -> list[str]:
    """Return list of namespace devices for given controller."""
    raw = run_cmd(f"nvme list -o json {dev}")
    namespaces = []
    try:
        parsed = json.loads(raw)
        for ns in parsed.get("Devices", []):
            for n in ns.get("Namespaces", []):
                namespaces.append(n["NameSpace"])
    except Exception:
        pass
    # fallback: assume at least n1
    if not namespaces:
        namespaces.append(dev + "n1")
    return namespaces


def get_device_info(dev: str) -> dict:
    """Gather NVMe + PCIe device details."""
    return {
        "device": dev,
        "nvme_list": run_cmd(f"nvme list {dev}"),
        "id_ctrl": run_cmd(f"nvme id-ctrl {dev}"),
        "pcie_info": run_cmd("lspci -vv | grep -A15 -i nvme")
    }


# ============================
# SMART Monitoring
# ============================
def get_nvme_health(ns: str) -> str:
    """Return SMART log (JSON format) for namespace device."""
    return run_cmd(f"nvme smart-log -o json {ns}")


def monitor_smart(ns: str, interval: int = 5, duration: int = 20) -> list[dict]:
    """Collect SMART logs periodically for duration seconds."""
    logs = []
    start = time.time()
    while time.time() - start < duration:
        try:
            raw = get_nvme_health(ns)
            j = json.loads(raw)
            logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "temperature": j.get("temperature", 0),
                "percentage_used": j.get("percentage_used", 0),
                "media_errors": j.get("media_errors", 0)
            })
        except Exception:
            pass
        time.sleep(interval)
    return logs


# ============================
# fio Performance Testing
# ============================
def run_fio_test(ns: str, runtime: int = 20, iodepth: int = 4, rw: str = "randread", bs: str = "4k") -> dict:
    """Run fio test on a given namespace and parse JSON output."""
    cmd = (
        f"fio --name=nvme_test --filename={ns} "
        f"--rw={rw} --bs={bs} --iodepth={iodepth} --runtime={runtime} "
        f"--time_based=1 --ioengine=io_uring --output-format=json"
    )
    raw = run_cmd(cmd)
    try:
        return json.loads(raw)
    except Exception:
        return {"error": raw}


def extract_fio_trends(fio_json: dict) -> dict:
    """Extract IOPS and latency values from fio JSON output."""
    trends = {"iops": [], "latency": []}
    if "jobs" not in fio_json:
        return trends

    for job in fio_json["jobs"]:
        read_iops = job["read"].get("iops", 0)
        write_iops = job["write"].get("iops", 0)
        trends["iops"].append(read_iops or write_iops)

        read_lat = job["read"].get("clat_ns", {}).get("mean", 0) / 1000.0
        write_lat = job["write"].get("clat_ns", {}).get("mean", 0) / 1000.0
        trends["latency"].append(read_lat or write_lat)

    return trends


# ============================
# Plotting
# ============================
def plot_smart_trends(logs: list[dict], metric: str, ylabel: str) -> str:
    """Plot SMART trend and return base64 PNG."""
    if not logs:
        return ""
    times = [entry["time"] for entry in logs]
    values = [entry.get(metric, 0) for entry in logs]

    fig, ax = plt.subplots(figsize=(6, 3))
    ax.plot(times, values, marker="o", linestyle="-")
    ax.set_title(f"{metric.replace('_',' ').title()} Trend")
    ax.set_ylabel(ylabel)
    ax.set_xticks(times)
    ax.set_xticklabels(times, rotation=45, fontsize=8)
    ax.grid(True)
    fig.tight_layout()
    return b64_plot(fig)


def plot_fio_trend(values: list, ylabel: str) -> str:
    """Plot fio performance trend and return base64 PNG."""
    if not values:
        return ""
    x = list(range(1, len(values) + 1))
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.plot(x, values, marker="o")
    ax.set_title(f"{ylabel} Trend")
    ax.set_xlabel("Interval")
    ax.set_ylabel(ylabel)
    ax.grid(True)
    fig.tight_layout()
    return b64_plot(fig)


def plot_combined_timeline(smart_logs: list[dict], fio_trends: dict) -> str:
    """Plot combined Temp, IOPS, and Latency vs Time."""
    if not smart_logs or not fio_trends["iops"]:
        return ""

    times = [entry["time"] for entry in smart_logs]
    temps = [entry["temperature"] for entry in smart_logs]

    fig, ax1 = plt.subplots(figsize=(7, 4))

    # Temperature
    ax1.set_xlabel("Time")
    ax1.set_ylabel("Temperature (¢XC)", color="tab:red")
    ax1.plot(times, temps, color="tab:red", marker="o", label="Temp")
    ax1.tick_params(axis="y", labelcolor="tab:red")
    ax1.set_xticklabels(times, rotation=45, fontsize=8)

    # Secondary axis for IOPS & Latency
    ax2 = ax1.twinx()
    ax2.set_ylabel("IOPS / Latency (us)", color="tab:blue")
    ax2.plot(times, fio_trends["iops"], color="tab:blue", marker="s", label="IOPS")
    if fio_trends["latency"]:
        ax2.plot(times, fio_trends["latency"], color="tab:green", marker="^", label="Latency")
    ax2.tick_params(axis="y", labelcolor="tab:blue")

    fig.tight_layout()
    return b64_plot(fig)


# ============================
# Parallel Worker
# ============================
def test_namespace(ns: str) -> dict:
    """Run SMART monitoring and fio workload for one namespace."""
    smart_logs = monitor_smart(ns, interval=5, duration=20)
    fio_json = run_fio_test(ns, runtime=20)
    fio_trends = extract_fio_trends(fio_json)
    return {"smart_logs": smart_logs, "fio_trends": fio_trends}


# ============================
# Report Generators
# ============================
def consolidate_results(devices: list[str], save_path: str = "./logs") -> tuple[str, dict]:
    """Run tests in parallel across namespaces, save JSON."""
    Path(save_path).mkdir(parents=True, exist_ok=True)
    results = {}

    for dev in devices:
        namespaces = list_nvme_namespaces(dev)
        dev_data = {"info": get_device_info(dev), "namespaces": {}}

        # Run namespaces in parallel
        with ThreadPoolExecutor(max_workers=len(namespaces)) as executor:
            future_map = {executor.submit(test_namespace, ns): ns for ns in namespaces}
            for future in as_completed(future_map):
                ns = future_map[future]
                try:
                    dev_data["namespaces"][ns] = future.result()
                except Exception as e:
                    dev_data["namespaces"][ns] = {"error": str(e)}

        results[dev] = dev_data

    filepath = os.path.join(save_path, f"ssd_report_{timestamp()}.json")
    save_json(results, filepath)
    return filepath, results


def generate_html_report(results: dict, save_path: str = "./logs") -> str:
    """Generate HTML report with SMART + FIO charts per namespace."""
    Path(save_path).mkdir(parents=True, exist_ok=True)
    html_file = os.path.join(save_path, f"ssd_report_{timestamp()}.html")

    html = """<html><head><title>NVMe SSD Report</title></head><body>
    <h1>Enterprise NVMe PCIe Gen5 SSD Report</h1><hr>"""

    for dev, data in results.items():
        html += f"<h2>Controller: {dev}</h2>"
        html += "<h3>Device Info</h3><pre>{}</pre>".format(data["info"])

        for ns, ns_data in data["namespaces"].items():
            html += f"<h3>Namespace: {ns}</h3>"

            if ns_data.get("smart_logs"):
                html += "<h4>SMART Trends</h4>"
                for metric, ylabel in [("temperature", "Temp (¢XC)"),
                                       ("percentage_used", "% Used"),
                                       ("media_errors", "Media Errors")]:
                    b64 = plot_smart_trends(ns_data["smart_logs"], metric, ylabel)
                    if b64:
                        html += f"<p>{metric}</p><img src='data:image/png;base64,{b64}'/>"

            if ns_data.get("fio_trends"):
                html += "<h4>FIO Performance Trends</h4>"
                if ns_data["fio_trends"]["iops"]:
                    b64 = plot_fio_trend(ns_data["fio_trends"]["iops"], "IOPS")
                    html += f"<p>IOPS</p><img src='data:image/png;base64,{b64}'/>"
                if ns_data["fio_trends"]["latency"]:
                    b64 = plot_fio_trend(ns_data["fio_trends"]["latency"], "Latency (us)")
                    html += f"<p>Latency</p><img src='data:image/png;base64,{b64}'/>"

                combined = plot_combined_timeline(ns_data["smart_logs"], ns_data["fio_trends"])
                if combined:
                    html += "<h4>Combined Timeline (Temp vs IOPS vs Latency)</h4>"
                    html += f"<img src='data:image/png;base64,{combined}'/>"

        html += "<hr>"

    html += "</body></html>"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html)

    return html_file


# ============================
# Usage Example
# ============================
def usage_examples():
    devices = list_nvme_devices()
    print(f"Detected NVMe Devices: {devices}")

    if not devices:
        print("No NVMe devices found.")
        return

    json_report, results = consolidate_results(devices)
    print(f"JSON report saved: {json_report}")

    html_report = generate_html_report(results)
    print(f"HTML report saved: {html_report}")


# ============================
# Main Entry
# ============================
def main():
    usage_examples()


if __name__ == "__main__":
    main()
