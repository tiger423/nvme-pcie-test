#!/usr/bin/env python3
"""
NVMe Filesystem Operations Sample
Create, mount, and test filesystems on NVMe namespaces
"""

import sys
import os
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.common import (print_header, print_section, list_nvme_devices_nvme_cli, 
                         run_cmd, controller_from_ns, check_sudo_access, confirm_action)

def create_filesystem(namespace: str, fs_type: str = "ext4", force: bool = False):
    print_section(f"Creating {fs_type} filesystem on {namespace}")
    
    if not check_sudo_access():
        print("Error: Root access required for filesystem operations")
        return False
    
    if not force:
        print(f"⚠️  WARNING: This will destroy any existing data on {namespace}")
        if not confirm_action(f"Create {fs_type} filesystem on {namespace}?"):
            print("Filesystem creation cancelled")
            return False
    
    if fs_type == "ext4":
        mkfs_cmd = f"mkfs.ext4 -F {namespace}"
    elif fs_type == "xfs":
        mkfs_cmd = f"mkfs.xfs -f {namespace}"
    elif fs_type == "btrfs":
        mkfs_cmd = f"mkfs.btrfs -f {namespace}"
    else:
        print(f"Unsupported filesystem type: {fs_type}")
        return False
    
    print(f"Creating filesystem: {mkfs_cmd}")
    result = run_cmd(mkfs_cmd, require_root=True)
    
    if result.startswith("Error:"):
        print(f"❌ Filesystem creation failed: {result}")
        return False
    else:
        print("✅ Filesystem created successfully")
        print(result)
        return True

def mount_namespace(namespace: str, mountpoint: str):
    print_section(f"Mounting {namespace} to {mountpoint}")
    
    if not check_sudo_access():
        print("Error: Root access required for mount operations")
        return False
    
    os.makedirs(mountpoint, exist_ok=True)
    
    if os.path.ismount(mountpoint):
        print(f"⚠️  {mountpoint} is already a mount point")
        return False
    
    mount_cmd = f"mount {namespace} {mountpoint}"
    result = run_cmd(mount_cmd, require_root=True)
    
    if result.startswith("Error:"):
        print(f"❌ Mount failed: {result}")
        return False
    else:
        print("✅ Mounted successfully")
        return True

def unmount_path(mountpoint: str):
    print_section(f"Unmounting {mountpoint}")
    
    if not check_sudo_access():
        print("Error: Root access required for unmount operations")
        return False
    
    if not os.path.ismount(mountpoint):
        print(f"⚠️  {mountpoint} is not a mount point")
        return False
    
    umount_cmd = f"umount {mountpoint}"
    result = run_cmd(umount_cmd, require_root=True)
    
    if result.startswith("Error:"):
        print(f"❌ Unmount failed: {result}")
        return False
    else:
        print("✅ Unmounted successfully")
        return True

def test_filesystem(mountpoint: str, test_size: str = "100M"):
    print_section(f"Testing filesystem at {mountpoint}")
    
    if not os.path.ismount(mountpoint):
        print(f"❌ {mountpoint} is not mounted")
        return False
    
    test_file = os.path.join(mountpoint, "nvme_test_file")
    
    print(f"Creating test file of size {test_size}...")
    dd_cmd = f"dd if=/dev/zero of={test_file} bs=1M count={test_size.rstrip('M')} oflag=direct"
    result = run_cmd(dd_cmd, require_root=True)
    
    if result.startswith("Error:"):
        print(f"❌ Test file creation failed: {result}")
        return False
    
    print("✅ Test file created successfully")
    
    print("Reading test file...")
    read_cmd = f"dd if={test_file} of=/dev/null bs=1M iflag=direct"
    result = run_cmd(read_cmd, require_root=True)
    
    if result.startswith("Error:"):
        print(f"❌ Test file read failed: {result}")
        return False
    
    print("✅ Test file read successfully")
    
    print("Removing test file...")
    rm_result = run_cmd(f"rm -f {test_file}", require_root=True)
    
    if not rm_result.startswith("Error:"):
        print("✅ Test file removed")
    
    return True

def show_filesystem_info(namespace: str):
    print_section(f"Filesystem Information: {namespace}")
    
    blkid_result = run_cmd(f"blkid {namespace}")
    if not blkid_result.startswith("Error:"):
        print("Block device info:")
        print(blkid_result)
    
    lsblk_result = run_cmd(f"lsblk {namespace}")
    if not lsblk_result.startswith("Error:"):
        print("\nBlock device tree:")
        print(lsblk_result)
    
    df_result = run_cmd(f"df -h {namespace}")
    if not df_result.startswith("Error:"):
        print("\nDisk usage:")
        print(df_result)

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
    parser = argparse.ArgumentParser(description="NVMe Filesystem Operations")
    parser.add_argument("--namespace", help="Namespace to operate on (e.g., /dev/nvme0n1)")
    parser.add_argument("--mountpoint", default="/mnt/nvme_test", help="Mount point directory")
    parser.add_argument("--fs-type", default="ext4", choices=["ext4", "xfs", "btrfs"], 
                       help="Filesystem type")
    parser.add_argument("--test-size", default="100M", help="Test file size")
    parser.add_argument("--create-fs", action="store_true", help="Create filesystem")
    parser.add_argument("--mount", action="store_true", help="Mount filesystem")
    parser.add_argument("--unmount", action="store_true", help="Unmount filesystem")
    parser.add_argument("--test", action="store_true", help="Test filesystem")
    parser.add_argument("--info", action="store_true", help="Show filesystem info")
    parser.add_argument("--full-cycle", action="store_true", help="Full cycle: create, mount, test, unmount")
    args = parser.parse_args()
    
    namespace = args.namespace
    if not namespace:
        namespace = select_namespace()
        if not namespace:
            print("No namespace selected")
            return
    
    if args.info:
        show_filesystem_info(namespace)
        return
    
    if args.full_cycle:
        print_header("Full Filesystem Test Cycle")
        
        print("Step 1: Create filesystem")
        if not create_filesystem(namespace, args.fs_type):
            return
        
        print("\nStep 2: Mount filesystem")
        if not mount_namespace(namespace, args.mountpoint):
            return
        
        print("\nStep 3: Test filesystem")
        test_filesystem(args.mountpoint, args.test_size)
        
        print("\nStep 4: Unmount filesystem")
        unmount_path(args.mountpoint)
        
        print("\n✅ Full filesystem test cycle completed")
        return
    
    if args.create_fs:
        create_filesystem(namespace, args.fs_type)
    
    if args.mount:
        mount_namespace(namespace, args.mountpoint)
    
    if args.test:
        test_filesystem(args.mountpoint, args.test_size)
    
    if args.unmount:
        unmount_path(args.mountpoint)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
