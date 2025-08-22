#!/usr/bin/env python3
"""
Enterprise NVMe PCIe Gen5 SSD QA Test Framework
Python 3.12 + Ubuntu 24.04 Compatible
Features:
- NVMe device detection
- SMART log monitoring with trend charts
- fio performance testing with trend charts
- Combined timeline chart (Temp vs IOPS vs Latency)
- JSON + HTML reporting (self-contained)
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
# Device Manager
# ============================
def list_nvme_devices() -> list[str]:
    """Detect NVMe devices using nvme-cli JSON output."""
    raw = run_cmd("nvme list -o json")
    try:
        devices = json.loads(raw).get("Devices", [])
        return [d["DevicePath"] for d in devices]
    except Exception:
        return []


def get_device_info(dev: str) -> dict:
    """Gather NVMe + PCIe device details."""
    return {
        "device": dev,
        "nvme_list": run_cmd(f"nvme list {dev}"),
        "id_ctrl": run_cmd(f"nvme id-ctrl {dev}"),
        "id_ns": run_cmd(f"nvme id-ns {dev} -n 1"),
        "pcie_info": run_cmd("lspci -vv | grep -A15 -i nvme")
    }


# ============================
# SMART Monitoring
# ============================
def get_nvme_health(dev: str) -> str:
    """Return SMART log (JSON format)."""
    return run_cmd(f"nvme smart-log -o json {dev}")


def monitor_smart(dev: str, interval: int = 10, duration: int = 60) -> list[dict]:
    """Collect SMART logs periodically for duration seconds."""
    logs = []
    start = time.time()
    while time.time() - start < duration:
        try:
            raw = get_nvme_health(dev)
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
def run_fio_test(dev: str, runtime: int = 60, iodepth: int = 4, rw: str = "randread", bs: str = "4k") -> dict:
    """Run fio test on NVMe device and parse JSON output."""
    cmd = (
        f"fio --name=nvme_test --filename={dev}n1 "
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
# Report Generators
# ============================
def consolidate_results(devices: list[str], save_path: str = "./logs") -> tuple[str, dict]:
    """Collect device info, SMART logs, fio results, save JSON."""
    Path(save_path).mkdir(parents=True, exist_ok=True)
    results = {}
    for dev in devices:
        fio_json = run_fio_test(dev, runtime=30)
        fio_trends = extract_fio_trends(fio_json)
        results[dev] = {
            "info": get_device_info(dev),
            "smart_logs": monitor_smart(dev, interval=10, duration=30),
            "fio_trends": fio_trends
        }
    filepath = os.path.join(save_path, f"ssd_report_{timestamp()}.json")
    save_json(results, filepath)
    return filepath, results


def generate_html_report(results: dict, save_path: str = "./logs") -> str:
    """Generate HTML report with SMART + FIO charts."""
    Path(save_path).mkdir(parents=True, exist_ok=True)
    html_file = os.path.join(save_path, f"ssd_report_{timestamp()}.html")

    html = """<html><head><title>NVMe SSD Report</title></head><body>
    <h1>Enterprise NVMe PCIe Gen5 SSD Report</h1><hr>"""

    for dev, data in results.items():
        html += f"<h2>Device: {dev}</h2>"
        html += "<h3>Device Info</h3><pre>{}</pre>".format(data["info"])

        if data.get("smart_logs"):
            html += "<h3>SMART Trends</h3>"
            for metric, ylabel in [("temperature", "Temp (¢XC)"),
                                   ("percentage_used", "% Used"),
                                   ("media_errors", "Media Errors")]:
                b64 = plot_smart_trends(data["smart_logs"], metric, ylabel)
                if b64:
                    html += f"<h4>{metric}</h4><img src='data:image/png;base64,{b64}'/>"

        if data.get("fio_trends"):
            html += "<h3>FIO Performance Trends</h3>"
            if data["fio_trends"]["iops"]:
                b64 = plot_fio_trend(data["fio_trends"]["iops"], "IOPS")
                html += f"<h4>IOPS</h4><img src='data:image/png;base64,{b64}'/>"
            if data["fio_trends"]["latency"]:
                b64 = plot_fio_trend(data["fio_trends"]["latency"], "Latency (us)")
                html += f"<h4>Latency</h4><img src='data:image/png;base64,{b64}'/>"

            # Combined chart
            combined = plot_combined_timeline(data["smart_logs"], data["fio_trends"])
            if combined:
                html += "<h3>Combined Timeline (Temp vs IOPS vs Latency)</h3>"
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
