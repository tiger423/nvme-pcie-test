#!/usr/bin/env python3
"""
NVMe QA Testing Menu System
Interactive menu for accessing individual NVMe testing functions
"""

import os
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils.common import print_header, check_sudo_access, list_nvme_devices_nvme_cli

def show_menu():
    print_header("NVMe QA Testing Menu")
    print("1.  Device Discovery & Listing")
    print("2.  Device Information & PCI Details")
    print("3.  SMART Health Monitoring")
    print("4.  SMART Health Monitoring + CSV Export")
    print("5.  FIO Performance Testing")
    print("6.  Namespace Formatting")
    print("7.  Controller Sanitization")
    print("8.  Filesystem Operations")
    print("9.  Power State Monitoring")
    print("10. System Telemetry Collection")
    print("11. Report Generation & Visualization")
    print("12. Debug SMART Data")
    print("13. Run Full QA Suite (Original)")
    print("0.  Exit")
    print("-" * 60)

def get_device_parameters(sample_name: str):
    """Get appropriate device parameters for samples that need them"""
    controllers, namespaces = list_nvme_devices_nvme_cli()
    
    namespace_samples = ["03_smart_monitoring.py", "04_health_csv_export.py", 
                        "06_formatting.py", "08_filesystem_ops.py"]
    controller_samples = ["07_sanitization.py", "09_power_monitoring.py", "10_telemetry.py"]
    target_samples = ["05_fio_performance.py"]
    
    if sample_name in namespace_samples:
        if namespaces:
            return ["--namespace", namespaces[0]]
    elif sample_name in controller_samples:
        if controllers:
            return ["--controller", controllers[0]]
    elif sample_name in target_samples:
        if namespaces:
            return ["--target", namespaces[0]]
        elif controllers:
            return ["--target", controllers[0]]
    
    return []

def run_sample(sample_name: str):
    sample_path = Path(__file__).parent / "samples" / sample_name
    if not sample_path.exists():
        print(f"Error: Sample {sample_name} not found")
        return
    
    cmd = [sys.executable, str(sample_path)]
    device_params = get_device_parameters(sample_name)
    cmd.extend(device_params)
    
    need_sudo = bool(device_params) and check_sudo_access()
    if need_sudo:
        cmd = ["sudo", "-E"] + cmd
        print(f"Running with sudo: {' '.join(cmd)}")
        print("You may be prompted for your password...")
    
    try:
        if need_sudo:
            result = subprocess.run(cmd, check=True)
        else:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if result.stdout:
                print(result.stdout, end='')
            if result.stderr:
                print(result.stderr, end='')
    except subprocess.CalledProcessError as e:
        print(f"Error running sample (exit code {e.returncode})")
        if hasattr(e, 'stdout') and e.stdout:
            print("STDOUT:", e.stdout)
        if hasattr(e, 'stderr') and e.stderr:
            print("STDERR:", e.stderr)
        print(f"Command: {' '.join(e.cmd)}")
    except Exception as e:
        print(f"Unexpected error running sample: {type(e).__name__}: {e}")
    except KeyboardInterrupt:
        print("\nSample interrupted by user")

def run_original_qa():
    original_script = Path(__file__).parent / "nvme-qa.py"
    if not original_script.exists():
        print("Error: Original nvme-qa.py not found")
        return
    
    config_file = Path(__file__).parent / "config.yaml"
    if config_file.exists():
        cmd = [sys.executable, str(original_script), "--config", str(config_file)]
    else:
        cmd = [sys.executable, str(original_script)]
    
    if check_sudo_access():
        cmd.append("--sudo")
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running original QA suite: {e}")
    except KeyboardInterrupt:
        print("\nQA suite interrupted by user")

def main():
    while True:
        show_menu()
        try:
            choice = input("Select option [0-13]: ").strip()
            
            if choice == "0":
                print("Goodbye!")
                break
            elif choice == "1":
                run_sample("01_device_discovery.py")
            elif choice == "2":
                run_sample("02_device_info.py")
            elif choice == "3":
                run_sample("03_smart_monitoring.py")
            elif choice == "4":
                run_sample("04_health_csv_export.py")
            elif choice == "5":
                run_sample("05_fio_performance.py")
            elif choice == "6":
                run_sample("06_formatting.py")
            elif choice == "7":
                run_sample("07_sanitization.py")
            elif choice == "8":
                run_sample("08_filesystem_ops.py")
            elif choice == "9":
                run_sample("09_power_monitoring.py")
            elif choice == "10":
                run_sample("10_telemetry.py")
            elif choice == "11":
                run_sample("11_report_generation.py")
            elif choice == "12":
                run_sample("debug_smart.py")
            elif choice == "13":
                run_original_qa()
            else:
                print("Invalid choice. Please select 0-13.")
            
            if choice != "0":
                input("\nPress Enter to continue...")
                print()
        
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except EOFError:
            print("\nGoodbye!")
            break

if __name__ == "__main__":
    main()
