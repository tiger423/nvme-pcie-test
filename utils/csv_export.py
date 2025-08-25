#!/usr/bin/env python3
"""
CSV export utilities for NVMe QA test results
"""

import csv
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from .common import timestamp, get_temperature_celsius

def ensure_csv_dir(filepath: str) -> str:
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    return filepath

def save_to_csv(data: List[Dict], filepath: str, fieldnames: Optional[List[str]] = None) -> str:
    if not data:
        return "No data to save"
    
    filepath = ensure_csv_dir(filepath)
    
    if fieldnames is None:
        fieldnames = list(data[0].keys())
    
    try:
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in data:
                filtered_row = {k: v for k, v in row.items() if k in fieldnames}
                writer.writerow(filtered_row)
        return f"Successfully saved {len(data)} rows to {filepath}"
    except Exception as e:
        return f"Error saving CSV: {e}"

def save_health_data_csv(health_logs: List[Dict], device_info: Dict, filepath: str) -> str:
    if not health_logs:
        return "No health data to save"
    
    enhanced_data = []
    for log in health_logs:
        row = {
            'timestamp': log.get('time', ''),
            'device': device_info.get('namespace', 'unknown'),
            'controller': device_info.get('controller', 'unknown'),
            'model': device_info.get('model', 'unknown'),
            'serial': device_info.get('serial', 'unknown'),
            'temperature_c': get_temperature_celsius(log),
            'percentage_used': log.get('percentage_used', 0),
            'media_errors': log.get('media_errors', 0),
            'critical_warnings': log.get('critical_warnings', 0)
        }
        enhanced_data.append(row)
    
    fieldnames = ['timestamp', 'device', 'controller', 'model', 'serial', 
                  'temperature_c', 'percentage_used', 'media_errors', 'critical_warnings']
    
    return save_to_csv(enhanced_data, filepath, fieldnames)

def save_performance_data_csv(fio_results: Dict, device: str, filepath: str) -> str:
    if not fio_results or 'jobs' not in fio_results:
        return "No performance data to save"
    
    perf_data = []
    for job in fio_results.get('jobs', []):
        read_data = job.get('read', {})
        write_data = job.get('write', {})
        
        if read_data.get('iops', 0) > 0:
            row = {
                'timestamp': timestamp(),
                'device': device,
                'workload': 'read',
                'iops': read_data.get('iops', 0),
                'latency_us': read_data.get('clat_ns', {}).get('mean', 0) / 1000.0,
                'bandwidth_mbps': read_data.get('bw', 0) / 1024.0,
                'runtime_sec': job.get('runtime', 0) / 1000.0
            }
            perf_data.append(row)
        
        if write_data.get('iops', 0) > 0:
            row = {
                'timestamp': timestamp(),
                'device': device,
                'workload': 'write',
                'iops': write_data.get('iops', 0),
                'latency_us': write_data.get('clat_ns', {}).get('mean', 0) / 1000.0,
                'bandwidth_mbps': write_data.get('bw', 0) / 1024.0,
                'runtime_sec': job.get('runtime', 0) / 1000.0
            }
            perf_data.append(row)
    
    fieldnames = ['timestamp', 'device', 'workload', 'iops', 'latency_us', 'bandwidth_mbps', 'runtime_sec']
    return save_to_csv(perf_data, filepath, fieldnames)

def save_device_info_csv(devices_info: List[Dict], filepath: str) -> str:
    if not devices_info:
        return "No device info to save"
    
    device_data = []
    for info in devices_info:
        row = {
            'controller': info.get('controller', 'unknown'),
            'namespace': info.get('namespace', 'unknown'),
            'pci_bdf': info.get('pci_bdf', 'unknown'),
            'model': info.get('model', 'unknown'),
            'serial': info.get('serial', 'unknown'),
            'firmware': info.get('firmware', 'unknown'),
            'link_speed': info.get('link_speed', 'unknown'),
            'link_width': info.get('link_width', 'unknown')
        }
        device_data.append(row)
    
    fieldnames = ['controller', 'namespace', 'pci_bdf', 'model', 'serial', 'firmware', 'link_speed', 'link_width']
    return save_to_csv(device_data, filepath, fieldnames)

def append_to_csv(data: Dict, filepath: str, fieldnames: List[str]) -> str:
    filepath = ensure_csv_dir(filepath)
    
    file_exists = os.path.exists(filepath)
    
    try:
        with open(filepath, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            
            filtered_row = {k: v for k, v in data.items() if k in fieldnames}
            writer.writerow(filtered_row)
        
        return f"Successfully appended data to {filepath}"
    except Exception as e:
        return f"Error appending to CSV: {e}"

def get_csv_filepath(base_name: str, subdir: str = "csv_exports") -> str:
    return os.path.join(subdir, f"{base_name}_{timestamp()}.csv")
