#!/usr/bin/env python3
"""
NVMe Namespace Formatting Sample
Safe namespace formatting with confirmations
"""

import sys
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.common import (print_header, print_section, list_nvme_devices_nvme_cli, 
                         run_cmd, controller_from_ns, check_sudo_access, confirm_action)

def get_namespace_info(namespace: str):
    print_section(f"Namespace Information: {namespace}")
    
    id_ns_output = run_cmd(f"nvme id-ns {namespace}")
    print("Namespace Details:")
    print(id_ns_output)
    
    ctrl = controller_from_ns(namespace)
    id_ctrl_output = run_cmd(f"nvme id-ctrl {ctrl}")
    if not id_ctrl_output.startswith("Error:"):
        print(f"\nController Details ({ctrl}):")
        print(id_ctrl_output[:500] + "..." if len(id_ctrl_output) > 500 else id_ctrl_output)

def format_namespace(namespace: str, lbaf: int = 0, ses: int = 0, wait_after: int = 5):
    print_header(f"Formatting Namespace: {namespace}")
    
    if not check_sudo_access():
        print("Error: Root access required for formatting operations")
        return False
    
    print(f"Format parameters:")
    print(f"  LBA Format: {lbaf}")
    print(f"  Secure Erase Setting: {ses}")
    print(f"  Wait after format: {wait_after}s")
    
    print("\n⚠️  CRITICAL WARNING ⚠️")
    print("This operation will PERMANENTLY ERASE ALL DATA on the namespace!")
    print("Make sure you have backed up any important data.")
    print(f"Target namespace: {namespace}")
    
    if not confirm_action("Are you absolutely sure you want to format this namespace?"):
        print("Format operation cancelled")
        return False
    
    if not confirm_action("This is your FINAL WARNING. Proceed with format?"):
        print("Format operation cancelled")
        return False
    
    print("\nStarting format operation...")
    
    format_cmd = f"nvme format {namespace} --lbaf={lbaf} --ses={ses}"
    result = run_cmd(format_cmd, require_root=True)
    
    if result.startswith("Error:"):
        print(f"Format failed with direct command, trying controller method...")
        
        ctrl = controller_from_ns(namespace)
        nsid_match = __import__('re').search(r'n(\d+)$', namespace)
        if nsid_match:
            nsid = nsid_match.group(1)
            fallback_cmd = f"nvme format {ctrl} -n {nsid} --lbaf={lbaf} --ses={ses}"
            result = run_cmd(fallback_cmd, require_root=True)
    
    print(f"Format result: {result}")
    
    if not result.startswith("Error:"):
        print(f"Waiting {wait_after} seconds for format to complete...")
        time.sleep(wait_after)
        
        print("Verifying format completion...")
        verify_result = run_cmd(f"nvme id-ns {namespace}")
        if not verify_result.startswith("Error:"):
            print("✅ Format completed successfully")
            return True
        else:
            print("⚠️  Format may have completed but verification failed")
            return False
    else:
        print("❌ Format operation failed")
        return False

def list_lba_formats(namespace: str):
    print_section("Available LBA Formats")
    
    ctrl = controller_from_ns(namespace)
    id_ns_output = run_cmd(f"nvme id-ns {namespace} -H")
    
    if not id_ns_output.startswith("Error:"):
        print("Namespace LBA formats:")
        print(id_ns_output)
    else:
        print("Could not retrieve LBA format information")

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
            choice = input(f"\nSelect namespace to format [1-{len(namespaces)}]: ").strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(namespaces):
                    return namespaces[idx]
            print("Invalid selection")
        except (ValueError, KeyboardInterrupt):
            return None

def main():
    parser = argparse.ArgumentParser(description="NVMe Namespace Formatting")
    parser.add_argument("--namespace", help="Namespace to format (e.g., /dev/nvme0n1)")
    parser.add_argument("--lbaf", type=int, default=0, help="LBA format index")
    parser.add_argument("--ses", type=int, default=0, help="Secure erase setting")
    parser.add_argument("--wait", type=int, default=5, help="Wait time after format")
    parser.add_argument("--info-only", action="store_true", help="Show namespace info only")
    args = parser.parse_args()
    
    namespace = args.namespace
    if not namespace:
        namespace = select_namespace()
        if not namespace:
            print("No namespace selected")
            return
    
    if args.info_only:
        get_namespace_info(namespace)
        list_lba_formats(namespace)
        return
    
    get_namespace_info(namespace)
    list_lba_formats(namespace)
    
    success = format_namespace(namespace, args.lbaf, args.ses, args.wait)
    
    if success:
        print("\n✅ Namespace formatting completed successfully")
    else:
        print("\n❌ Namespace formatting failed")

if __name__ == "__main__":
    main()
