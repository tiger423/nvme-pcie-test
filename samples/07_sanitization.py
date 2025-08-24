#!/usr/bin/env python3
"""
NVMe Controller Sanitization Sample
Safe controller sanitization with confirmations
"""

import sys
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.common import (print_header, print_section, list_nvme_devices_nvme_cli, 
                         run_cmd, controller_from_ns, check_sudo_access, confirm_action)

def get_controller_info(controller: str):
    print_section(f"Controller Information: {controller}")
    
    id_ctrl_output = run_cmd(f"nvme id-ctrl {controller}")
    if not id_ctrl_output.startswith("Error:"):
        print("Controller Details:")
        print(id_ctrl_output[:800] + "..." if len(id_ctrl_output) > 800 else id_ctrl_output)
    else:
        print(f"Error getting controller info: {id_ctrl_output}")

def sanitize_controller(controller: str, action: str = "block", ause: bool = False, 
                       owpass: int = 1, interval: int = 5, timeout: int = 600):
    print_header(f"Sanitizing Controller: {controller}")
    
    if not check_sudo_access():
        print("Error: Root access required for sanitization operations")
        return False
    
    if action == "none":
        print("Sanitization skipped (action=none)")
        return True
    
    sanact_map = {"block": 1, "overwrite": 2, "crypto": 3}
    if action not in sanact_map:
        print(f"Error: Invalid sanitization action '{action}'. Use: block, overwrite, crypto, none")
        return False
    
    sanact = sanact_map[action]
    
    print(f"Sanitization parameters:")
    print(f"  Action: {action} (sanact={sanact})")
    print(f"  Allow Unrestricted Sanitize Exit: {ause}")
    print(f"  Overwrite Pass Count: {owpass}")
    print(f"  Progress check interval: {interval}s")
    print(f"  Timeout: {timeout}s")
    
    print("\n🚨 CRITICAL WARNING 🚨")
    print("This operation will PERMANENTLY AND IRREVERSIBLY ERASE ALL DATA")
    print("on the ENTIRE CONTROLLER and ALL its namespaces!")
    print("This includes:")
    print("- All user data")
    print("- All metadata")
    print("- All encryption keys (if crypto sanitize)")
    print("- ALL namespaces on this controller")
    print(f"Target controller: {controller}")
    
    if not confirm_action("Are you absolutely certain you want to sanitize this controller?"):
        print("Sanitization cancelled")
        return False
    
    if not confirm_action("This will DESTROY ALL DATA. Type 'DESTROY' to confirm"):
        print("Sanitization cancelled")
        return False
    
    final_confirm = input("Type 'DESTROY ALL DATA' to proceed: ").strip()
    if final_confirm != "DESTROY ALL DATA":
        print("Sanitization cancelled - confirmation text did not match")
        return False
    
    print("\nStarting sanitization operation...")
    
    cmd_parts = [f"nvme sanitize {controller}", f"--sanact={sanact}"]
    if ause:
        cmd_parts.append("--ause")
    if action == "overwrite":
        cmd_parts.append(f"--owpass={owpass}")
    
    sanitize_cmd = " ".join(cmd_parts)
    print(f"Command: {sanitize_cmd}")
    
    result = run_cmd(sanitize_cmd, require_root=True)
    print(f"Sanitize start result: {result}")
    
    if result.startswith("Error:"):
        print("❌ Failed to start sanitization")
        return False
    
    print("✅ Sanitization started successfully")
    print("Monitoring progress...")
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        time.sleep(interval)
        
        progress_result = run_cmd(f"nvme sanitize-log {controller}")
        if not progress_result.startswith("Error:"):
            print(f"[{time.strftime('%H:%M:%S')}] Progress check:")
            print(progress_result[:200] + "..." if len(progress_result) > 200 else progress_result)
            
            if "Sanitize Progress" in progress_result and "100%" in progress_result:
                print("✅ Sanitization completed successfully!")
                return True
            elif "No sanitize operation in progress" in progress_result:
                print("✅ Sanitization completed!")
                return True
        else:
            print(f"[{time.strftime('%H:%M:%S')}] Progress check failed: {progress_result}")
    
    print(f"⚠️  Sanitization timeout after {timeout}s - operation may still be in progress")
    print("Check sanitization status manually with: nvme sanitize-log <controller>")
    return False

def check_sanitize_status(controller: str):
    print_section(f"Sanitization Status: {controller}")
    
    status_result = run_cmd(f"nvme sanitize-log {controller}")
    if not status_result.startswith("Error:"):
        print("Sanitization Log:")
        print(status_result)
    else:
        print(f"Error checking status: {status_result}")

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
            choice = input(f"\nSelect controller to sanitize [1-{len(controllers)}]: ").strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(controllers):
                    return controllers[idx]
            print("Invalid selection")
        except (ValueError, KeyboardInterrupt):
            return None

def main():
    parser = argparse.ArgumentParser(description="NVMe Controller Sanitization")
    parser.add_argument("--controller", help="Controller to sanitize (e.g., /dev/nvme0)")
    parser.add_argument("--action", default="block", 
                       choices=["block", "overwrite", "crypto", "none"],
                       help="Sanitization action")
    parser.add_argument("--ause", action="store_true", 
                       help="Allow Unrestricted Sanitize Exit")
    parser.add_argument("--owpass", type=int, default=1, 
                       help="Overwrite pass count (for overwrite action)")
    parser.add_argument("--interval", type=int, default=5, 
                       help="Progress check interval in seconds")
    parser.add_argument("--timeout", type=int, default=600, 
                       help="Operation timeout in seconds")
    parser.add_argument("--status-only", action="store_true", 
                       help="Check sanitization status only")
    args = parser.parse_args()
    
    controller = args.controller
    if not controller:
        controller = select_controller()
        if not controller:
            print("No controller selected")
            return
    
    if args.status_only:
        check_sanitize_status(controller)
        return
    
    get_controller_info(controller)
    
    success = sanitize_controller(controller, args.action, args.ause, 
                                args.owpass, args.interval, args.timeout)
    
    if success:
        print("\n✅ Controller sanitization completed successfully")
    else:
        print("\n❌ Controller sanitization failed or timed out")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
