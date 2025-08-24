#!/usr/bin/env python3
"""
NVMe FIO Performance Testing Sample
Single workload performance testing with CSV export
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.common import (print_header, print_section, list_nvme_devices_nvme_cli, 
                         run_cmd, controller_from_ns, check_sudo_access)
from utils.csv_export import save_performance_data_csv, get_csv_filepath

def run_fio_test(target: str, workload: str = "randread", runtime: int = 30, 
                 iodepth: int = 4, bs: str = "4k", ioengine: str = "io_uring"):
    print_header(f"FIO Performance Test: {workload}")
    print(f"Target: {target}")
    print(f"Runtime: {runtime}s, IO Depth: {iodepth}, Block Size: {bs}")
    print(f"IO Engine: {ioengine}\n")
    
    if not check_sudo_access():
        print("Warning: This test may require sudo access for direct device access")
    
    fio_cmd = (
        f"fio --name=nvme_perf_test --filename={target} "
        f"--rw={workload} --bs={bs} --iodepth={iodepth} --runtime={runtime} "
        f"--time_based=1 --ioengine={ioengine} --output-format=json --direct=1"
    )
    
    print("Running FIO test...")
    print(f"Command: {fio_cmd}\n")
    
    raw_output = run_cmd(fio_cmd, require_root=True)
    
    if raw_output.startswith("Error:"):
        print(f"FIO test failed: {raw_output}")
        return None
    
    try:
        fio_results = json.loads(raw_output)
        return fio_results
    except json.JSONDecodeError as e:
        print(f"Failed to parse FIO output: {e}")
        print(f"Raw output: {raw_output[:500]}...")
        return None

def display_results(fio_results: dict, workload: str):
    if not fio_results or 'jobs' not in fio_results:
        print("No valid results to display")
        return
    
    print_section("Performance Results")
    
    for job in fio_results.get('jobs', []):
        read_data = job.get('read', {})
        write_data = job.get('write', {})
        
        if workload in ['read', 'randread'] or 'read' in workload:
            if read_data.get('iops', 0) > 0:
                print(f"Read IOPS: {read_data['iops']:,.0f}")
                print(f"Read Bandwidth: {read_data.get('bw', 0) / 1024:.2f} MB/s")
                print(f"Read Latency (avg): {read_data.get('clat_ns', {}).get('mean', 0) / 1000:.2f} μs")
        
        if workload in ['write', 'randwrite'] or 'write' in workload:
            if write_data.get('iops', 0) > 0:
                print(f"Write IOPS: {write_data['iops']:,.0f}")
                print(f"Write Bandwidth: {write_data.get('bw', 0) / 1024:.2f} MB/s")
                print(f"Write Latency (avg): {write_data.get('clat_ns', {}).get('mean', 0) / 1000:.2f} μs")
        
        if 'randrw' in workload or 'rw' in workload:
            if read_data.get('iops', 0) > 0:
                print(f"Read IOPS: {read_data['iops']:,.0f}")
                print(f"Read Bandwidth: {read_data.get('bw', 0) / 1024:.2f} MB/s")
            if write_data.get('iops', 0) > 0:
                print(f"Write IOPS: {write_data['iops']:,.0f}")
                print(f"Write Bandwidth: {write_data.get('bw', 0) / 1024:.2f} MB/s")
        
        runtime_ms = job.get('runtime', 0)
        print(f"Actual Runtime: {runtime_ms / 1000:.1f}s")

def select_target():
    controllers, namespaces = list_nvme_devices_nvme_cli()
    
    if not namespaces:
        print("No NVMe namespaces found")
        return None
    
    print("Available targets:")
    all_targets = namespaces + controllers
    
    for i, target in enumerate(all_targets, 1):
        if target in namespaces:
            ctrl = controller_from_ns(target)
            print(f"{i}. {target} (Namespace on {ctrl})")
        else:
            print(f"{i}. {target} (Controller)")
    
    while True:
        try:
            choice = input(f"\nSelect target [1-{len(all_targets)}]: ").strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(all_targets):
                    return all_targets[idx]
            print("Invalid selection")
        except (ValueError, KeyboardInterrupt):
            return None

def main():
    parser = argparse.ArgumentParser(description="NVMe FIO Performance Testing")
    parser.add_argument("--target", help="Target device (namespace or controller)")
    parser.add_argument("--workload", default="randread", 
                       choices=["randread", "randwrite", "read", "write", "randrw"],
                       help="FIO workload type")
    parser.add_argument("--runtime", type=int, default=30, help="Test runtime in seconds")
    parser.add_argument("--iodepth", type=int, default=4, help="IO queue depth")
    parser.add_argument("--bs", default="4k", help="Block size")
    parser.add_argument("--ioengine", default="io_uring", help="IO engine")
    parser.add_argument("--csv", action="store_true", help="Export results to CSV")
    args = parser.parse_args()
    
    target = args.target
    if not target:
        target = select_target()
        if not target:
            print("No target selected")
            return
    
    print("⚠️  WARNING: This test will perform I/O operations on the selected device.")
    print("Make sure you have backed up any important data.")
    
    confirm = input("Continue? (y/N): ").strip().lower()
    if confirm not in ['y', 'yes']:
        print("Test cancelled")
        return
    
    fio_results = run_fio_test(target, args.workload, args.runtime, 
                              args.iodepth, args.bs, args.ioengine)
    
    if fio_results:
        display_results(fio_results, args.workload)
        
        if args.csv:
            csv_path = get_csv_filepath(f"fio_performance_{args.workload}")
            result = save_performance_data_csv(fio_results, target, csv_path)
            print(f"\nCSV Export: {result}")
    else:
        print("Test failed or produced no results")

if __name__ == "__main__":
    main()
