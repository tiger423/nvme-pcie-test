#!/usr/bin/env python3
"""
Debug SMART Data Structure
Inspect raw SMART data to troubleshoot temperature issues
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.common import (print_header, list_nvme_devices_nvme_cli, 
                         debug_smart_data, controller_from_ns)

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
    print_header("SMART Data Debug Tool")
    
    namespace = select_namespace()
    if not namespace:
        print("No namespace selected")
        return
    
    print(f"\nDebugging SMART data for: {namespace}")
    debug_smart_data(namespace)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
