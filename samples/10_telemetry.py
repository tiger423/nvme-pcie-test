#!/usr/bin/env python3
"""
NVMe System Telemetry Collection Sample
Collect system sensors, turbostat, and NVMe telemetry data
"""

import sys
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.common import (print_header, print_section, list_nvme_devices_nvme_cli, 
                         run_cmd, controller_from_ns, time_hms, cmd_exists)
from utils.csv_export import save_to_csv, get_csv_filepath

def collect_sensors_data():
    print_section("System Sensors Data")
    
    if not cmd_exists("sensors"):
        print("⚠️  lm-sensors not available. Install with: sudo apt install lm-sensors")
        return None
    
    sensors_output = run_cmd("sensors -A -j")
    if sensors_output.startswith("Error:"):
        print(f"Error collecting sensors data: {sensors_output}")
        return None
    
    try:
        import json
        sensors_data = json.loads(sensors_output)
        print("✅ Sensors data collected successfully")
        return sensors_data
    except json.JSONDecodeError:
        print("⚠️  Failed to parse sensors JSON output")
        return None

def collect_turbostat_data(duration: int = 10):
    print_section("Turbostat Data Collection")
    
    if not cmd_exists("turbostat"):
        print("⚠️  turbostat not available. May require kernel tools installation")
        return None
    
    print(f"Running turbostat for {duration} seconds...")
    turbostat_cmd = f"timeout {duration} turbostat --quiet --show Core,CPU,Avg_MHz,Busy%,Bzy_MHz,TSC_MHz,IRQ,C1,C1E,C3,C6,C7s,C8,C9,C10,Pkg%pc2,Pkg%pc3,Pkg%pc6,Pkg%pc7,PkgTmp,CoreTmp --interval 1"
    
    turbostat_output = run_cmd(turbostat_cmd, require_root=True)
    
    if turbostat_output.startswith("Error:"):
        print(f"Error collecting turbostat data: {turbostat_output}")
        return None
    
    print("✅ Turbostat data collected successfully")
    return turbostat_output

def collect_nvme_telemetry(controller: str):
    print_section(f"NVMe Telemetry Log: {controller}")
    
    telemetry_cmd = f"nvme telemetry-log {controller} --output-format=json"
    telemetry_output = run_cmd(telemetry_cmd)
    
    if telemetry_output.startswith("Error:"):
        print(f"Error collecting NVMe telemetry: {telemetry_output}")
        return None
    
    try:
        import json
        telemetry_data = json.loads(telemetry_output)
        print("✅ NVMe telemetry collected successfully")
        return telemetry_data
    except json.JSONDecodeError:
        print("⚠️  Failed to parse telemetry JSON output")
        return telemetry_output

def monitor_system_telemetry(duration: int = 60, interval: int = 10):
    print_header("System Telemetry Monitoring")
    print(f"Monitoring for {duration} seconds with {interval}s intervals")
    print("Press Ctrl+C to stop early\n")
    
    telemetry_logs = []
    start_time = time.time()
    
    try:
        while time.time() - start_time < duration:
            try:
                log_entry = {
                    "time": time_hms(),
                    "timestamp": time.time()
                }
                
                sensors_data = collect_sensors_data()
                if sensors_data:
                    log_entry["sensors"] = sensors_data
                
                print(f"[{log_entry['time']}] Telemetry data collected")
                telemetry_logs.append(log_entry)
                
                time.sleep(interval)
                
            except KeyboardInterrupt:
                print("\nMonitoring stopped by user")
                break
            except Exception as e:
                print(f"[{time_hms()}] Error: {e}")
                time.sleep(interval)
    
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user")
    
    return telemetry_logs

def extract_temperature_data(sensors_data):
    temperatures = {}
    
    if not sensors_data:
        return temperatures
    
    for chip_name, chip_data in sensors_data.items():
        if isinstance(chip_data, dict):
            for sensor_name, sensor_data in chip_data.items():
                if isinstance(sensor_data, dict) and "temp" in sensor_name.lower():
                    for reading_name, reading_value in sensor_data.items():
                        if "input" in reading_name and isinstance(reading_value, (int, float)):
                            temp_key = f"{chip_name}_{sensor_name}"
                            temperatures[temp_key] = reading_value
    
    return temperatures

def show_telemetry_summary(telemetry_logs):
    if not telemetry_logs:
        print("No telemetry data to summarize")
        return
    
    print_section("Telemetry Summary")
    print(f"Total readings: {len(telemetry_logs)}")
    
    all_temps = []
    for log in telemetry_logs:
        if "sensors" in log:
            temps = extract_temperature_data(log["sensors"])
            all_temps.extend(temps.values())
    
    if all_temps:
        print(f"Temperature readings: {len(all_temps)}")
        print(f"Temperature range: {min(all_temps):.1f}°C - {max(all_temps):.1f}°C")
        print(f"Average temperature: {sum(all_temps)/len(all_temps):.1f}°C")

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
    parser = argparse.ArgumentParser(description="NVMe System Telemetry Collection")
    parser.add_argument("--controller", help="Controller for NVMe telemetry (e.g., /dev/nvme0)")
    parser.add_argument("--duration", type=int, default=60, help="Monitoring duration in seconds")
    parser.add_argument("--interval", type=int, default=10, help="Monitoring interval in seconds")
    parser.add_argument("--sensors-only", action="store_true", help="Collect sensors data only")
    parser.add_argument("--turbostat-only", action="store_true", help="Collect turbostat data only")
    parser.add_argument("--nvme-telemetry-only", action="store_true", help="Collect NVMe telemetry only")
    parser.add_argument("--csv", action="store_true", help="Export results to CSV")
    args = parser.parse_args()
    
    if args.sensors_only:
        sensors_data = collect_sensors_data()
        if sensors_data:
            print("Sensors data collected successfully")
            if args.csv:
                csv_data = [{"time": time_hms(), "sensors": str(sensors_data)}]
                csv_path = get_csv_filepath("sensors_data")
                result = save_to_csv(csv_data, csv_path)
                print(f"CSV Export: {result}")
        return
    
    if args.turbostat_only:
        turbostat_data = collect_turbostat_data(args.duration)
        if turbostat_data:
            print("Turbostat data:")
            print(turbostat_data[:1000] + "..." if len(turbostat_data) > 1000 else turbostat_data)
            if args.csv:
                csv_data = [{"time": time_hms(), "turbostat": turbostat_data}]
                csv_path = get_csv_filepath("turbostat_data")
                result = save_to_csv(csv_data, csv_path)
                print(f"CSV Export: {result}")
        return
    
    if args.nvme_telemetry_only:
        controller = args.controller
        if not controller:
            controller = select_controller()
            if not controller:
                print("No controller selected")
                return
        
        nvme_telemetry = collect_nvme_telemetry(controller)
        if nvme_telemetry:
            print("NVMe telemetry collected successfully")
            if args.csv:
                csv_data = [{"time": time_hms(), "controller": controller, "telemetry": str(nvme_telemetry)}]
                csv_path = get_csv_filepath("nvme_telemetry")
                result = save_to_csv(csv_data, csv_path)
                print(f"CSV Export: {result}")
        return
    
    telemetry_logs = monitor_system_telemetry(args.duration, args.interval)
    
    if telemetry_logs:
        show_telemetry_summary(telemetry_logs)
        
        if args.csv:
            csv_path = get_csv_filepath("system_telemetry")
            result = save_to_csv(telemetry_logs, csv_path)
            print(f"\nCSV Export: {result}")
    else:
        print("No telemetry data collected")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
