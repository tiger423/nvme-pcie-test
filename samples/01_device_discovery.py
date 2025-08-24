#!/usr/bin/env python3
"""
NVMe Device Discovery Sample
Lists all NVMe controllers and namespaces with optional CSV export
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.common import print_header, print_section, list_nvme_devices_nvme_cli, re_filter, controller_from_ns
from utils.csv_export import save_device_info_csv, get_csv_filepath

def list_controllers_and_namespaces(include_regex=".*", exclude_regex=""):
    print_header("NVMe Device Discovery")
    
    controllers, namespaces = list_nvme_devices_nvme_cli()
    
    if not controllers and not namespaces:
        print("No NVMe devices found. Make sure nvme-cli is installed and devices are present.")
        return [], []
    
    filtered_controllers = re_filter(controllers, include_regex, exclude_regex)
    filtered_namespaces = re_filter(namespaces, include_regex, exclude_regex)
    
    print_section("Controllers Found")
    if filtered_controllers:
        for i, ctrl in enumerate(filtered_controllers, 1):
            print(f"{i:2d}. {ctrl}")
    else:
        print("No controllers found matching criteria")
    
    print_section("Namespaces Found")
    if filtered_namespaces:
        for i, ns in enumerate(filtered_namespaces, 1):
            ctrl = controller_from_ns(ns)
            print(f"{i:2d}. {ns} (Controller: {ctrl})")
    else:
        print("No namespaces found matching criteria")
    
    return filtered_controllers, filtered_namespaces

def export_to_csv(controllers, namespaces):
    device_info = []
    
    for ctrl in controllers:
        ctrl_namespaces = [ns for ns in namespaces if controller_from_ns(ns) == ctrl]
        if ctrl_namespaces:
            for ns in ctrl_namespaces:
                device_info.append({
                    'controller': ctrl,
                    'namespace': ns,
                    'pci_bdf': 'unknown',
                    'model': 'unknown',
                    'serial': 'unknown',
                    'firmware': 'unknown',
                    'link_speed': 'unknown',
                    'link_width': 'unknown'
                })
        else:
            device_info.append({
                'controller': ctrl,
                'namespace': 'none',
                'pci_bdf': 'unknown',
                'model': 'unknown',
                'serial': 'unknown',
                'firmware': 'unknown',
                'link_speed': 'unknown',
                'link_width': 'unknown'
            })
    
    if device_info:
        csv_path = get_csv_filepath("device_discovery")
        result = save_device_info_csv(device_info, csv_path)
        print(f"\nCSV Export: {result}")
    else:
        print("\nNo device data to export")

def main():
    parser = argparse.ArgumentParser(description="NVMe Device Discovery")
    parser.add_argument("--include", default=".*", help="Include regex pattern")
    parser.add_argument("--exclude", default="", help="Exclude regex pattern")
    parser.add_argument("--csv", action="store_true", help="Export results to CSV")
    args = parser.parse_args()
    
    controllers, namespaces = list_controllers_and_namespaces(args.include, args.exclude)
    
    if args.csv:
        export_to_csv(controllers, namespaces)
    
    print(f"\nSummary: Found {len(controllers)} controllers and {len(namespaces)} namespaces")

if __name__ == "__main__":
    main()
