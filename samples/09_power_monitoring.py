#!/usr/bin/env python3
"""
NVMe Power State Monitoring Sample
Monitor power states and power consumption
"""

import sys
import time
import re
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.common import (print_header, print_section, list_nvme_devices_nvme_cli, 
                         run_cmd, controller_from_ns, time_hms)
from utils.csv_export import save_to_csv, get_csv_filepath

def parse_power_value(txt: str):
    m = re.search(r"Current value:\s*(0x[0-9A-Fa-f]+|\d+)", txt)
    if not m:
        return None
    token = m.group(1)
    try:
        return int(token, 0)
    except Exception:
        return None

def get_power_state_value(ctrl: str):
    result = run_cmd(f"nvme get-feature {ctrl} -f 2 -H")
    if result.startswith("Error:"):
        return None
    return parse_power_value(result)

def monitor_power_states(controller: str, interval: int = 5, duration: int = 60):
    print_header(f"Power State Monitoring: {controller}")
    print(f"Monitoring for {duration} seconds with {interval}s intervals")
    print("Press Ctrl+C to stop early\n")
    
    power_logs = []
    start_time = time.time()
    
    try:
        while time.time() - start_time < duration:
            try:
                power_value = get_power_state_value(controller)
                
                log_entry = {
                    "time": time_hms(),
                    "controller": controller,
                    "power_state_value": power_value if power_value is not None else "unknown",
                    "timestamp": time.time()
                }
                
                power_logs.append(log_entry)
                
                print(f"[{log_entry['time']}] Power State Value: {log_entry['power_state_value']}")
                
                time.sleep(interval)
                
            except KeyboardInterrupt:
                print("\nMonitoring stopped by user")
                break
            except Exception as e:
                print(f"[{time_hms()}] Error: {e}")
                time.sleep(interval)
    
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user")
    
    return power_logs

def get_power_management_info(controller: str):
    print_section(f"Power Management Information: {controller}")
    
    print("Power State Descriptors:")
    ps_result = run_cmd(f"nvme id-ctrl {controller} -H")
    if not ps_result.startswith("Error:"):
        lines = ps_result.split('\n')
        in_ps_section = False
        for line in lines:
            if "Power State Descriptors" in line:
                in_ps_section = True
            elif in_ps_section and line.strip():
                if line.startswith("ps"):
                    print(f"  {line}")
                elif not line.startswith(" "):
                    break
    
    print("\nCurrent Power State Feature:")
    current_ps = run_cmd(f"nvme get-feature {controller} -f 2 -H")
    if not current_ps.startswith("Error:"):
        print(current_ps)
    
    print("\nAutonomous Power State Transition:")
    apst_result = run_cmd(f"nvme get-feature {controller} -f 12 -H")
    if not apst_result.startswith("Error:"):
        print(apst_result)

def set_power_state(controller: str, power_state: int):
    print_section(f"Setting Power State: {controller}")
    
    if not (0 <= power_state <= 31):
        print("Error: Power state must be between 0 and 31")
        return False
    
    print(f"Setting power state to: {power_state}")
    result = run_cmd(f"nvme set-feature {controller} -f 2 -v {power_state}")
    
    if result.startswith("Error:"):
        print(f"❌ Failed to set power state: {result}")
        return False
    else:
        print("✅ Power state set successfully")
        print(result)
        return True

def select_controller():
    controllers, _ = list_nvme_devices_nvme_cli()
    
    if not controllers:
        print("No NVMe controllers found")
        return None
    
    print("Available controllers:")
    for i, ctrl in enumerate(controllers, 1):
        print(f"{i}. {ctrl}")
    
    while True:
        try:
            choice = input(f"\nSelect controller [1-{len(controllers)}]: ").strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(controllers):
                    return controllers[idx]
            print("Invalid selection")
        except (ValueError, KeyboardInterrupt):
            return None

def main():
    parser = argparse.ArgumentParser(description="NVMe Power State Monitoring")
    parser.add_argument("--controller", help="Controller to monitor (e.g., /dev/nvme0)")
    parser.add_argument("--interval", type=int, default=5, help="Monitoring interval in seconds")
    parser.add_argument("--duration", type=int, default=60, help="Monitoring duration in seconds")
    parser.add_argument("--set-ps", type=int, help="Set power state (0-31)")
    parser.add_argument("--info-only", action="store_true", help="Show power management info only")
    parser.add_argument("--csv", action="store_true", help="Export results to CSV")
    args = parser.parse_args()
    
    controller = args.controller
    if not controller:
        controller = select_controller()
        if not controller:
            print("No controller selected")
            return
    
    if args.info_only:
        get_power_management_info(controller)
        return
    
    if args.set_ps is not None:
        set_power_state(controller, args.set_ps)
        return
    
    get_power_management_info(controller)
    
    power_logs = monitor_power_states(controller, args.interval, args.duration)
    
    if power_logs:
        print(f"\nCollected {len(power_logs)} power state readings")
        
        print_section("Summary")
        power_values = [log['power_state_value'] for log in power_logs if log['power_state_value'] != "unknown"]
        if power_values:
            print(f"Power state values: Min={min(power_values)}, Max={max(power_values)}")
            print(f"Most common power state: {max(set(power_values), key=power_values.count)}")
        else:
            print("No valid power state values collected")
        
        if args.csv:
            csv_path = get_csv_filepath("power_monitoring")
            result = save_to_csv(power_logs, csv_path)
            print(f"\nCSV Export: {result}")
    else:
        print("No data collected")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
