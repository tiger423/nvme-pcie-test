#!/usr/bin/env python3
"""
NVMe Device Information Sample
Shows detailed device information including PCI details
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.common import (print_header, print_section, list_nvme_devices_nvme_cli, 
                         run_cmd, controller_from_ns)
from utils.csv_export import save_device_info_csv, get_csv_filepath

def get_pci_bdf_for_ctrl(ctrl: str):
    import os
    import re
    
    name = os.path.basename(ctrl)
    bdf_re_full = re.compile(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]")
    
    sys_node = f"/sys/class/nvme/{name}/device"
    if os.path.exists(sys_node):
        try:
            real_path = os.path.realpath(sys_node)
            match = bdf_re_full.search(real_path)
            if match:
                return match.group(0)
        except Exception:
            pass
    
    return None

def get_device_detailed_info(ctrl: str):
    info = {"controller": ctrl}
    
    bdf = get_pci_bdf_for_ctrl(ctrl)
    info["pci_bdf"] = bdf or "unknown"
    
    if bdf:
        base = f"/sys/bus/pci/devices/{bdf}"
        try:
            with open(f"{base}/current_link_speed", "r") as f:
                info["current_link_speed"] = f.read().strip()
        except:
            info["current_link_speed"] = "unknown"
        
        try:
            with open(f"{base}/current_link_width", "r") as f:
                info["current_link_width"] = f.read().strip()
        except:
            info["current_link_width"] = "unknown"
        
        lspci_output = run_cmd(f"lspci -s {bdf} -v")
        info["lspci_output"] = lspci_output
    
    id_ctrl_output = run_cmd(f"nvme id-ctrl -o json {ctrl}")
    try:
        id_ctrl_json = json.loads(id_ctrl_output)
        info["model"] = id_ctrl_json.get("mn", "unknown").strip()
        info["serial"] = id_ctrl_json.get("sn", "unknown").strip()
        info["firmware"] = id_ctrl_json.get("fr", "unknown").strip()
    except:
        info["model"] = "unknown"
        info["serial"] = "unknown"
        info["firmware"] = "unknown"
    
    return info

def show_device_info(device=None):
    print_header("NVMe Device Information")
    
    controllers, namespaces = list_nvme_devices_nvme_cli()
    
    if not controllers:
        print("No NVMe controllers found")
        return []
    
    if device:
        if device in controllers:
            selected_controllers = [device]
        elif device in namespaces:
            selected_controllers = [controller_from_ns(device)]
        else:
            print(f"Device {device} not found")
            return []
    else:
        selected_controllers = controllers
    
    device_infos = []
    
    for ctrl in selected_controllers:
        print_section(f"Controller: {ctrl}")
        
        info = get_device_detailed_info(ctrl)
        device_infos.append(info)
        
        print(f"PCI BDF: {info['pci_bdf']}")
        print(f"Model: {info['model']}")
        print(f"Serial: {info['serial']}")
        print(f"Firmware: {info['firmware']}")
        print(f"Link Speed: {info.get('current_link_speed', 'unknown')}")
        print(f"Link Width: {info.get('current_link_width', 'unknown')}")
        
        ctrl_namespaces = [ns for ns in namespaces if controller_from_ns(ns) == ctrl]
        if ctrl_namespaces:
            print("Namespaces:")
            for ns in ctrl_namespaces:
                print(f"  - {ns}")
        
        if info.get("lspci_output") and not info["lspci_output"].startswith("Error:"):
            print("\nPCI Details:")
            print(info["lspci_output"][:500] + "..." if len(info["lspci_output"]) > 500 else info["lspci_output"])
        
        print()
    
    return device_infos

def main():
    parser = argparse.ArgumentParser(description="NVMe Device Information")
    parser.add_argument("--device", help="Specific device to query (controller or namespace)")
    parser.add_argument("--csv", action="store_true", help="Export results to CSV")
    args = parser.parse_args()
    
    device_infos = show_device_info(args.device)
    
    if args.csv and device_infos:
        csv_data = []
        for info in device_infos:
            csv_data.append({
                'controller': info['controller'],
                'namespace': 'multiple',
                'pci_bdf': info['pci_bdf'],
                'model': info['model'],
                'serial': info['serial'],
                'firmware': info['firmware'],
                'link_speed': info.get('current_link_speed', 'unknown'),
                'link_width': info.get('current_link_width', 'unknown')
            })
        
        csv_path = get_csv_filepath("device_info")
        result = save_device_info_csv(csv_data, csv_path)
        print(f"CSV Export: {result}")

if __name__ == "__main__":
    main()
