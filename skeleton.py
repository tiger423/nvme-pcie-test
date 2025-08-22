
#!/usr/bin/env python3
"""
Enterprise NVMe PCIe Gen5 SSD QA Test Framework
Skeleton Code with Modular Structure
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
    """Detect available NVMe devices"""
    devs = []
    for d in os.listdir("/dev/"):
        if d.startswith("nvme") and "n" not in d:  # only controllers
            devs.append(f"/dev/{d}")
    return devs

def get_device_info(dev):
    """Gather NVMe + PCIe device details"""
    info = {
        "device": dev,
        "basic": run_cmd(f"nvme list | grep {dev}"),
        "id_ctrl": run_cmd(f"nvme id-ctrl {dev}"),
        "id_ns": run_cmd(f"nvme id-ns {dev} -n 1"),
        "pcie_info": run_cmd(f"lspci -vv -d 8086: | grep -A15 {dev[-1]}")  # placeholder
    }
    return info

# ============================
# Status Collector
# ============================
def get_pcie_link_status(dev):
    return run_cmd(f"sudo lspci -vv -s $(basename {dev})")

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
    """Monitor SMART during workload"""
    logs = []
    start = time.time()
    while time.time() - start < duration:
        logs.append(get_nvme_health(dev))
        time.sleep(interval)
    return logs

def check_thermal_throttling(dev):
    """Check if device is in thermal throttling state"""
    health = get_nvme_health(dev)
    if "temperature" in health and "Warning" in health:
        return "Thermal Throttling Detected"
    return "Normal"

def inject_pcie_error(dev):
    """Placeholder for PCIe AER / ECRC error injection hooks"""
    return "PCIe error injection not implemented in skeleton"

# ============================
# Report Consolidation
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
    return filepath

# ============================
# Main Workflow
# ============================
def main():
    devices = list_nvme_devices()
    print(f"Detected NVMe Devices: {devices}")

    for dev in devices:
        print(f"\n=== Processing {dev} ===")
        info = get_device_info(dev)
        print(info)

        status = collect_full_status(dev)
        print(status)

        # Example: format & mount
        format_device(dev, nsid=1, lbaf=0)
        wait_for_format_completion(dev)
        verify_format(dev)

        create_filesystem(dev, "ext4")
        mount_device(dev, "/mnt/nvme_test")
        check_fs_integrity("/mnt/nvme_test")
        unmount_device("/mnt/nvme_test")

    # Save consolidated report
    report = consolidate_results(devices, save_path="./logs")
    print(f"\nConsolidated report saved at: {report}")

if __name__ == "__main__":
    main()
