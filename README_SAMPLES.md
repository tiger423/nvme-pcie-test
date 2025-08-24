# NVMe QA Testing Samples

This directory contains independent, workable samples for each major function in the NVMe QA testing framework.

## Quick Start

Run the interactive menu:
```bash
python3 nvme-menu.py
```

## Individual Samples

### 1. Device Discovery (`01_device_discovery.py`)
Lists all NVMe controllers and namespaces with optional filtering.

```bash
python3 samples/01_device_discovery.py --csv
python3 samples/01_device_discovery.py --include "nvme0" --exclude "test"
```

### 2. Device Information (`02_device_info.py`)
Shows detailed device information including PCI details.

```bash
python3 samples/02_device_info.py --device /dev/nvme0 --csv
```

### 3. SMART Monitoring (`03_smart_monitoring.py`)
Real-time SMART health data monitoring.

```bash
python3 samples/03_smart_monitoring.py --namespace /dev/nvme0n1 --duration 60 --csv
```

### 4. Critical Health Monitoring (`04_health_csv_export.py`)
**NEW**: Focused health monitoring with automatic CSV export.

```bash
# Single snapshot
python3 samples/04_health_csv_export.py --namespace /dev/nvme0n1

# Continuous monitoring
python3 samples/04_health_csv_export.py --namespace /dev/nvme0n1 --continuous --interval 30
```

### 5. FIO Performance Testing (`05_fio_performance.py`)
Single workload performance testing.

```bash
python3 samples/05_fio_performance.py --target /dev/nvme0n1 --workload randread --csv
```

### 6. Namespace Formatting (`06_formatting.py`)
Safe namespace formatting with confirmations.

```bash
# Show info only
python3 samples/06_formatting.py --namespace /dev/nvme0n1 --info-only

# Format (requires confirmation)
sudo python3 samples/06_formatting.py --namespace /dev/nvme0n1 --lbaf 0
```

## CSV Export Features

All samples support CSV export with the `--csv` flag. CSV files are automatically timestamped and saved to `./csv_exports/`.

### CSV Output Formats

**Health Data CSV:**
```csv
timestamp,device,controller,model,serial,temperature_c,percentage_used,media_errors,critical_warnings
2024-08-24_13:30:15,/dev/nvme0n1,/dev/nvme0,Samsung 980 PRO,S1234567,45,2,0,0
```

**Performance Data CSV:**
```csv
timestamp,device,workload,iops,latency_us,bandwidth_mbps,runtime_sec
2024-08-24_13:30:15,/dev/nvme0n1,randread,50000,80.5,195.3,30.0
```

**Device Info CSV:**
```csv
controller,namespace,pci_bdf,model,serial,firmware,link_speed,link_width
/dev/nvme0,/dev/nvme0n1,0000:01:00.0,Samsung 980 PRO,S1234567,1B2QEXM7,8.0 GT/s PCIe,x4
```

## Safety Features

- **Destructive Operation Warnings**: Clear warnings for format/sanitize operations
- **Device Validation**: Ensures devices exist before operations
- **Privilege Checks**: Verifies sudo access when needed
- **Interactive Confirmations**: Multiple confirmations for dangerous operations

## Configuration Files

Sample configurations are provided in `configs/`:
- `health_monitoring.yaml` - Health monitoring parameters
- `performance_test.yaml` - FIO test configurations

## Requirements

- Python 3.12+
- nvme-cli tools
- sudo access for privileged operations
- Optional: fio for performance testing

## Error Handling

All samples include comprehensive error handling:
- Graceful fallbacks for missing tools
- Clear error messages
- Safe operation cancellation
- Proper cleanup on interruption

## Integration with Original Framework

Sample #12 in the menu runs the original `nvme-qa.py` with full functionality. All samples are designed to complement, not replace, the original framework.
