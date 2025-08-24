#!/usr/bin/env python3
"""
NVMe Critical Health Monitoring with CSV Export
Focused on critical SSD health metrics with automatic CSV export
"""

import sys
import json
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.common import (print_header, print_section, list_nvme_devices_nvme_cli, 
                         get_nvme_health, time_hms, controller_from_ns, run_cmd, kelvin_to_celsius)
from utils.csv_export import save_health_data_csv, get_csv_filepath, append_to_csv

def get_device_identification(namespace: str):
    ctrl = controller_from_ns(namespace)
    id_ctrl_output = run_cmd(f"nvme id-ctrl -o json {ctrl}")
    
    device_info = {
        'namespace': namespace,
        'controller': ctrl,
        'model': 'unknown',
        'serial': 'unknown',
        'firmware': 'unknown'
    }
    
    try:
        id_ctrl_json = json.loads(id_ctrl_output)
        device_info['model'] = id_ctrl_json.get("mn", "unknown").strip()
        device_info['serial'] = id_ctrl_json.get("sn", "unknown").strip()
        device_info['firmware'] = id_ctrl_json.get("fr", "unknown").strip()
    except:
        pass
    
    return device_info

def get_critical_health_metrics(namespace: str):
    raw_health = get_nvme_health(namespace)
    if raw_health.startswith("Error:"):
        return None, raw_health
    
    try:
        health_data = json.loads(raw_health)
        
        metrics = {
            "time": time_hms(),
            "temperature": kelvin_to_celsius(health_data.get("temperature", 0)),
            "percentage_used": health_data.get("percentage_used", 0),
            "media_errors": health_data.get("media_errors", 0),
            "critical_warnings": health_data.get("critical_warning", 0),
            "power_on_hours": health_data.get("power_on_hours", 0),
            "unsafe_shutdowns": health_data.get("unsafe_shutdowns", 0),
            "data_units_read": health_data.get("data_units_read", 0),
            "data_units_written": health_data.get("data_units_written", 0)
        }
        
        return metrics, None
    except json.JSONDecodeError as e:
        return None, f"JSON decode error: {e}"

def assess_health_status(metrics):
    warnings = []
    
    temp = metrics.get('temperature', 0)
    if temp > 70:
        warnings.append(f"High temperature: {temp}°C")
    
    used = metrics.get('percentage_used', 0)
    if used > 80:
        warnings.append(f"High wear level: {used}%")
    
    errors = metrics.get('media_errors', 0)
    if errors > 0:
        warnings.append(f"Media errors detected: {errors}")
    
    critical = metrics.get('critical_warnings', 0)
    if critical > 0:
        warnings.append(f"Critical warnings: {critical}")
    
    return warnings

def continuous_monitoring(namespace: str, csv_path: str, interval: int = 10):
    print_header(f"Critical Health Monitoring: {namespace}")
    print(f"Monitoring every {interval} seconds")
    print(f"CSV output: {csv_path}")
    print("Press Ctrl+C to stop\n")
    
    device_info = get_device_identification(namespace)
    print(f"Device: {device_info['model']} (S/N: {device_info['serial']})")
    print(f"Firmware: {device_info['firmware']}\n")
    
    fieldnames = ['timestamp', 'device', 'controller', 'model', 'serial', 
                  'temperature_c', 'percentage_used', 'media_errors', 'critical_warnings',
                  'power_on_hours', 'unsafe_shutdowns', 'data_units_read', 'data_units_written']
    
    try:
        while True:
            metrics, error = get_critical_health_metrics(namespace)
            
            if error:
                print(f"[{time_hms()}] Error: {error}")
                time.sleep(interval)
                continue
            
            warnings = assess_health_status(metrics)
            
            status_indicator = "⚠️ " if warnings else "✅"
            print(f"[{metrics['time']}] {status_indicator} "
                  f"Temp: {metrics['temperature']}°C, "
                  f"Used: {metrics['percentage_used']}%, "
                  f"Errors: {metrics['media_errors']}")
            
            if warnings:
                for warning in warnings:
                    print(f"  WARNING: {warning}")
            
            csv_row = {
                'timestamp': metrics['time'],
                'device': device_info['namespace'],
                'controller': device_info['controller'],
                'model': device_info['model'],
                'serial': device_info['serial'],
                'temperature_c': metrics['temperature'],
                'percentage_used': metrics['percentage_used'],
                'media_errors': metrics['media_errors'],
                'critical_warnings': metrics['critical_warnings'],
                'power_on_hours': metrics['power_on_hours'],
                'unsafe_shutdowns': metrics['unsafe_shutdowns'],
                'data_units_read': metrics['data_units_read'],
                'data_units_written': metrics['data_units_written']
            }
            
            append_result = append_to_csv(csv_row, csv_path, fieldnames)
            if "Error" in append_result:
                print(f"  CSV Error: {append_result}")
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print(f"\nMonitoring stopped. Data saved to: {csv_path}")

def single_snapshot(namespace: str, csv_path: str):
    print_header(f"Health Snapshot: {namespace}")
    
    device_info = get_device_identification(namespace)
    metrics, error = get_critical_health_metrics(namespace)
    
    if error:
        print(f"Error: {error}")
        return
    
    print(f"Device: {device_info['model']} (S/N: {device_info['serial']})")
    print(f"Firmware: {device_info['firmware']}")
    
    print_section("Critical Health Metrics")
    print(f"Temperature: {metrics['temperature']}°C")
    print(f"Percentage Used: {metrics['percentage_used']}%")
    print(f"Media Errors: {metrics['media_errors']}")
    print(f"Critical Warnings: {metrics['critical_warnings']}")
    print(f"Power On Hours: {metrics['power_on_hours']}")
    print(f"Unsafe Shutdowns: {metrics['unsafe_shutdowns']}")
    print(f"Data Units Read: {metrics['data_units_read']}")
    print(f"Data Units Written: {metrics['data_units_written']}")
    
    warnings = assess_health_status(metrics)
    if warnings:
        print_section("Health Warnings")
        for warning in warnings:
            print(f"⚠️  {warning}")
    else:
        print("\n✅ No health warnings detected")
    
    health_logs = [metrics]
    result = save_health_data_csv(health_logs, device_info, csv_path)
    print(f"\nCSV Export: {result}")

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
    parser = argparse.ArgumentParser(description="NVMe Critical Health Monitoring with CSV Export")
    parser.add_argument("--namespace", help="Namespace to monitor (e.g., /dev/nvme0n1)")
    parser.add_argument("--interval", type=int, default=10, help="Monitoring interval in seconds")
    parser.add_argument("--continuous", action="store_true", help="Continuous monitoring mode")
    parser.add_argument("--output", help="CSV output file path")
    args = parser.parse_args()
    
    namespace = args.namespace
    if not namespace:
        namespace = select_namespace()
        if not namespace:
            print("No namespace selected")
            return
    
    csv_path = args.output or get_csv_filepath("critical_health")
    
    if args.continuous:
        continuous_monitoring(namespace, csv_path, args.interval)
    else:
        single_snapshot(namespace, csv_path)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
