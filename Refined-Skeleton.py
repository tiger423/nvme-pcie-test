
#!/usr/bin/env python3
"""
Enterprise NVMe PCIe Gen5 SSD QA Test Framework
Refined Skeleton: using nvme-cli for detection, HTML reporting, and usage examples.
"""

import os
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

# ============================
# Utility Functions
# ============================
def run_cmd(cmd):
    """Run a shell command and return stdout"""
    try:
        result = subprocess.run(cmd, shell=True, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"

def save_json(data, filepath):
    """Save dict data into JSON file"""
    with open(filepath, "w") as f:
        json.dump(data, f, indent=4)

def timestamp():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# ============================
# Device Manager
# ============================
def list_nvme_devices():
    """Detect NVMe devices using nvme-cli JSON output"""
    raw = run_cmd("nvme list -o json")
    try:
        devices = json.loads(raw).get("Devices", [])
        return [d["DevicePath"] for d in devices]
    except Exception:
        return []

def get_device_info(dev):
    """Gather NVMe + PCIe device details"""
    info = {
        "device": dev,
        "nvme_list": run_cmd(f"nvme list {dev}"),
        "id_ctrl": run_cmd(f"nvme id-ctrl {dev}"),
        "id_ns": run_cmd(f"nvme id-ns {dev} -n 1"),
        "pcie_info": run_cmd(f"lspci -vv | grep -A15 -i nvme")  # placeholder
    }
    return info

# ============================
# Status Collector
# ============================
def get_pcie_link_status(dev):
    return run_cmd(f"sudo lspci -vv | grep -A10 -i nvme")

def get_nvme_health(dev):
    return run_cmd(f"nvme smart-log {dev}")

def get_nvme_error_log(dev):
    return run_cmd(f"nvme error-log {dev}")

def get_device_wear_status(dev):
    return run_cmd(f"nvme smart-log-add {dev}")  # vendor dependent

def collect_full_status(dev):
    return {
        "device": dev,
        "pcie_status": get_pcie_link_status(dev),
        "health": get_nvme_health(dev),
        "error_log": get_nvme_error_log(dev),
        "wear": get_device_wear_status(dev),
    }

# ============================
# Format Manager
# ============================
def format_device(dev, nsid=1, lbaf=0, ses=0):
    return run_cmd(f"nvme format {dev} -n {nsid} -l {lbaf} -s {ses}")

def wait_for_format_completion(dev, timeout=600):
    start = time.time()
    while time.time() - start < timeout:
        if "in progress" not in run_cmd(f"nvme list | grep {dev}"):
            return True
        time.sleep(5)
    return False

def verify_format(dev):
    return run_cmd(f"nvme id-ns {dev} -n 1")

# ============================
# Filesystem Manager
# ============================
def create_filesystem(dev, fs_type="ext4"):
    return run_cmd(f"sudo mkfs.{fs_type} {dev}n1 -F")

def mount_device(dev, mount_point="/mnt/nvme_test"):
    Path(mount_point).mkdir(parents=True, exist_ok=True)
    return run_cmd(f"sudo mount {dev}n1 {mount_point}")

def unmount_device(mount_point="/mnt/nvme_test"):
    return run_cmd(f"sudo umount {mount_point}")

def check_fs_integrity(mount_point="/mnt/nvme_test"):
    return run_cmd(f"sudo fsck -n {mount_point}")

# ============================
# Enterprise Enhancements
# ============================
def monitor_smart(dev, interval=60, duration=600):
    logs = []
    start = time.time()
    while time.time() - start < duration:
        logs.append(get_nvme_health(dev))
        time.sleep(interval)
    return logs

def check_thermal_throttling(dev):
    health = get_nvme_health(dev)
    if "temperature" in health and "Warning" in health:
        return "Thermal Throttling Detected"
    return "Normal"

def inject_pcie_error(dev):
    return "PCIe error injection not implemented in skeleton"

# ============================
# Report Generators
# ============================
def consolidate_results(devices, save_path="./logs"):
    Path(save_path).mkdir(parents=True, exist_ok=True)
    results = {}
    for dev in devices:
        results[dev] = {
            "info": get_device_info(dev),
            "status": collect_full_status(dev),
            "thermal": check_thermal_throttling(dev),
        }
    filepath = os.path.join(save_path, f"ssd_report_{timestamp()}.json")
    save_json(results, filepath)
    return filepath, results

def generate_html_report(results, save_path="./logs"):
    Path(save_path).mkdir(parents=True, exist_ok=True)
    html_file = os.path.join(save_path, f"ssd_report_{timestamp()}.html")

    html = """<html><head><title>NVMe SSD Report</title></head><body>
    <h1>Enterprise NVMe PCIe Gen5 SSD Report</h1>
    <hr>"""

    for dev, data in results.items():
        html += f"<h2>Device: {dev}</h2>"
        html += f"<h3>Info</h3><pre>{data['info']}</pre>"
        html += f"<h3>Status</h3><pre>{data['status']}</pre>"
        html += f"<h3>Thermal</h3><p>{data['thermal']}</p><hr>"

    html += "</body></html>"

    with open(html_file, "w") as f:
        f.write(html)

    return html_file

# ============================
# Usage Examples
# ============================
def usage_examples():
    devices = list_nvme_devices()
    print(f"Detected NVMe Devices: {devices}")

    if not devices:
        print("No NVMe devices found.")
        return

    dev = devices[0]

    # Example 1: Get device info
    print("\n--- Device Info ---")
    print(get_device_info(dev))

    # Example 2: Collect full status
    print("\n--- Device Status ---")
    print(collect_full_status(dev))

    # Example 3: Format and verify
    print("\n--- Format Device ---")
    print(format_device(dev, nsid=1, lbaf=0))
    wait_for_format_completion(dev)
    print(verify_format(dev))

    # Example 4: Create FS and mount
    print("\n--- Filesystem ---")
    print(create_filesystem(dev, "ext4"))
    print(mount_device(dev, "/mnt/nvme_test"))
    print(check_fs_integrity("/mnt/nvme_test"))
    print(unmount_device("/mnt/nvme_test"))

    # Example 5: Consolidate + Report
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

