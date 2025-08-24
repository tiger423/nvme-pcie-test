#!/usr/bin/env python3
"""
NVMe SMART Health Monitoring Sample
Real-time monitoring of SMART health data
"""

import sys
import json
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.common import (print_header, print_section, list_nvme_devices_nvme_cli, 
                         get_nvme_health, time_hms, controller_from_ns)
from utils.csv_export import save_health_data_csv, get_csv_filepath

def monitor_smart_data(namespace: str, interval: int = 5, duration: int = 30):
    print_header(f"SMART Monitoring: {namespace}")
    print(f"Monitoring for {duration} seconds with {interval}s intervals")
    print("Press Ctrl+C to stop early\n")
    
    logs = []
    start_time = time.time()
    
    try:
        while time.time() - start_time < duration:
            try:
                raw_health = get_nvme_health(namespace)
                if raw_health.startswith("Error:"):
                    print(f"Error getting health data: {raw_health}")
                    time.sleep(interval)
                    continue
                
                health_data = json.loads(raw_health)
                
                log_entry = {
                    "time": time_hms(),
                    "temperature": health_data.get("temperature", 0),
                    "percentage_used": health_data.get("percentage_used", 0),
                    "media_errors": health_data.get("media_errors", 0),
                    "critical_warnings": health_data.get("critical_warning", 0),
                    "power_on_hours": health_data.get("power_on_hours", 0),
                    "unsafe_shutdowns": health_data.get("unsafe_shutdowns", 0)
                }
                
                logs.append(log_entry)
                
                print(f"[{log_entry['time']}] Temp: {log_entry['temperature']}°C, "
                      f"Used: {log_entry['percentage_used']}%, "
                      f"Errors: {log_entry['media_errors']}, "
                      f"Warnings: {log_entry['critical_warnings']}")
                
                time.sleep(interval)
                
            except json.JSONDecodeError:
                print(f"[{time_hms()}] Failed to parse SMART data")
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\nMonitoring stopped by user")
                break
            except Exception as e:
                print(f"[{time_hms()}] Error: {e}")
                time.sleep(interval)
    
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user")
    
    return logs

def select_namespace():
    controllers, namespaces = list_nvme_devices_nvme_cli()
    
    if not namespaces:
        print("No NVMe namespaces found")
        return None
    
    print("Available namespaces:")
    for i, ns in enumerate(namespaces, 1):
        ctrl = controller_from_ns(ns)
        print(f"{i}. {ns} (Controller: {ctrl})")
    
    while True:
        try:
            choice = input(f"\nSelect namespace [1-{len(namespaces)}]: ").strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(namespaces):
                    return namespaces[idx]
            print("Invalid selection")
        except (ValueError, KeyboardInterrupt):
            return None

def main():
    parser = argparse.ArgumentParser(description="NVMe SMART Health Monitoring")
    parser.add_argument("--namespace", help="Namespace to monitor (e.g., /dev/nvme0n1)")
    parser.add_argument("--interval", type=int, default=5, help="Monitoring interval in seconds")
    parser.add_argument("--duration", type=int, default=30, help="Monitoring duration in seconds")
    parser.add_argument("--csv", action="store_true", help="Export results to CSV")
    args = parser.parse_args()
    
    namespace = args.namespace
    if not namespace:
        namespace = select_namespace()
        if not namespace:
            print("No namespace selected")
            return
    
    logs = monitor_smart_data(namespace, args.interval, args.duration)
    
    if logs:
        print(f"\nCollected {len(logs)} SMART readings")
        
        print_section("Summary")
        temps = [log['temperature'] for log in logs]
        print(f"Temperature: Min={min(temps)}°C, Max={max(temps)}°C, Avg={sum(temps)/len(temps):.1f}°C")
        
        final_log = logs[-1]
        print(f"Final percentage used: {final_log['percentage_used']}%")
        print(f"Media errors: {final_log['media_errors']}")
        print(f"Critical warnings: {final_log['critical_warnings']}")
        
        if args.csv:
            device_info = {
                'namespace': namespace,
                'controller': controller_from_ns(namespace),
                'model': 'unknown',
                'serial': 'unknown'
            }
            csv_path = get_csv_filepath("smart_monitoring")
            result = save_health_data_csv(logs, device_info, csv_path)
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
