#!/usr/bin/env python3
"""
Common utilities extracted from nvme-qa.py for use in samples
"""

import os
import sys
import json
import subprocess
import re
import shlex
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

_ANSI_RE = re.compile(r"\x1B\[[0-9;?]*[ -/]*[@-~]")

def _strip_ansi(s: str) -> str:
    if not isinstance(s, str):
        return s
    return _ANSI_RE.sub("", s)

def _normalize_cr(s: str) -> str:
    if not s or "\r" not in s:
        return s
    fixed_lines: List[str] = []
    for line in s.splitlines(keepends=False):
        if "\r" in line:
            fixed_lines.append(line.split("\r")[-1])
        else:
            fixed_lines.append(line)
    return "\n".join(fixed_lines)

def _apply_backspaces(s: str) -> str:
    if not s or "\b" not in s:
        return s
    out_chars: List[str] = []
    for ch in s:
        if ch == "\b":
            if out_chars:
                out_chars.pop()
        else:
            out_chars.append(ch)
    return "".join(out_chars)

def sanitize_cmd_output(s: str) -> str:
    if not isinstance(s, str):
        return s
    s = _strip_ansi(s)
    s = _normalize_cr(s)
    s = _apply_backspaces(s)
    return s.replace("\x00", "").strip()

def cmd_exists(name: str) -> bool:
    return subprocess.call(f"command -v {shlex.quote(name)} >/dev/null 2>&1", shell=True) == 0

def run_cmd(cmd: str, require_root: bool = False) -> str:
    try:
        if require_root and os.geteuid() != 0:
            cmd = f"sudo -n {cmd}"
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True, check=True)
        return sanitize_cmd_output(result.stdout)
    except subprocess.CalledProcessError as e:
        return f"Error: {sanitize_cmd_output(e.stderr)}"

def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def time_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")

def nvme_list_json() -> Dict[str, Any]:
    raw = run_cmd("nvme list -o json")
    try:
        return json.loads(raw)
    except Exception:
        return {}

def list_nvme_devices_nvme_cli() -> Tuple[List[str], List[str]]:
    j = nvme_list_json()
    ctrls: set[str] = set()
    nss: List[str] = []
    for dev in j.get("Devices", []):
        dp = dev.get("DevicePath")
        if isinstance(dp, str) and dp.startswith("/dev/nvme"):
            if re.search(r"n\d+$", dp):
                nss.append(dp)
                ctrls.add(re.sub(r"n\d+$", "", dp))
            else:
                ctrls.add(dp)
    return sorted(ctrls), nss

def controller_from_ns(ns: str) -> str:
    return re.sub(r"n\d+$", "", ns)

def re_filter(values: List[str], include_regex: str, exclude_regex: str) -> List[str]:
    inc = re.compile(include_regex) if include_regex else None
    exc = re.compile(exclude_regex) if exclude_regex else None
    out: List[str] = []
    for v in values:
        if inc and not inc.search(v):
            continue
        if exc and exc.search(v):
            continue
        out.append(v)
    return out

def get_nvme_health(ns: str) -> str:
    return run_cmd(f"nvme smart-log -o json {ns}")

def kelvin_to_celsius(kelvin_temp: float) -> float:
    """Convert temperature from Kelvin to Celsius"""
    if kelvin_temp == 0:
        return 0  # Handle case where temperature is not available
    return kelvin_temp - 273.15

def debug_smart_data(ns: str) -> None:
    """Debug function to inspect raw SMART data structure"""
    raw_health = get_nvme_health(ns)
    if raw_health.startswith("Error:"):
        print(f"Error getting SMART data: {raw_health}")
        return
    
    try:
        health_data = json.loads(raw_health)
        print("=== Raw SMART Data Structure ===")
        for key, value in health_data.items():
            if "temp" in key.lower():
                print(f"{key}: {value} (type: {type(value)})")
        print("=== All SMART Fields ===")
        for key, value in health_data.items():
            print(f"{key}: {value}")
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")

def get_temperature_celsius(health_data: dict) -> float:
    """Extract and convert temperature from SMART data to Celsius"""
    temp_fields = [
        "temperature",           # Standard temperature field
        "composite_temperature", # Composite temperature
        "temperature_sensor_1",  # First temperature sensor
        "temp"                  # Alternative field name
    ]
    
    for field in temp_fields:
        if field in health_data:
            temp_value = health_data[field]
            if isinstance(temp_value, (int, float)) and temp_value > 0:
                if 250 <= temp_value <= 400:
                    return kelvin_to_celsius(temp_value)
                elif 0 <= temp_value <= 150:
                    return float(temp_value)
                print(f"Warning: Suspicious temperature value {temp_value} in field '{field}'")
    
    return 0.0

def check_sudo_access() -> bool:
    return os.geteuid() == 0 or subprocess.call("sudo -n true", shell=True) == 0

def print_header(title: str):
    print("=" * 60)
    print(f" {title}")
    print("=" * 60)

def print_section(title: str):
    print(f"\n--- {title} ---")

def confirm_action(message: str) -> bool:
    while True:
        response = input(f"{message} (y/N): ").strip().lower()
        if response in ['y', 'yes']:
            return True
        elif response in ['n', 'no', '']:
            return False
        else:
            print("Please enter 'y' or 'n'")

def load_samples_from_location(source_path: str, target_path: str = None) -> bool:
    """
    Load sample files from a specified location to current folder
    
    Args:
        source_path: Path to directory containing sample files  
        target_path: Optional target directory (defaults to './samples/')
    
    Returns:
        bool: True if successful, False otherwise
    """
    import shutil
    from pathlib import Path
    
    try:
        source_dir = Path(source_path).resolve()
        if not source_dir.exists():
            print(f"Error: Source directory '{source_path}' does not exist")
            return False
        
        if not source_dir.is_dir():
            print(f"Error: '{source_path}' is not a directory")
            return False
        
        # Default target is samples directory in current working directory
        if target_path is None:
            target_dir = Path.cwd() / "samples"
        else:
            target_dir = Path(target_path).resolve()
        
        # Create target directory if it doesn't exist
        target_dir.mkdir(parents=True, exist_ok=True)
        print(f"Target directory: {target_dir}")
        
        # Find Python files in source directory
        py_files = list(source_dir.glob("*.py"))
        if not py_files:
            print(f"No Python files found in '{source_path}'")
            return False
        
        print(f"Found {len(py_files)} Python files in source directory")
        
        copied_count = 0
        skipped_count = 0
        
        for py_file in py_files:
            target_file = target_dir / py_file.name
            
            # Check if file already exists
            if target_file.exists():
                if not confirm_action(f"File '{py_file.name}' already exists. Overwrite?"):
                    print(f"Skipped: {py_file.name}")
                    skipped_count += 1
                    continue
            
            try:
                # Copy file preserving permissions
                shutil.copy2(py_file, target_file)
                print(f"Copied: {py_file.name}")
                copied_count += 1
            except Exception as e:
                print(f"Error copying {py_file.name}: {e}")
                return False
        
        print(f"\nSummary: {copied_count} files copied, {skipped_count} files skipped")
        return copied_count > 0
        
    except Exception as e:
        print(f"Error loading samples: {e}")
        return False
