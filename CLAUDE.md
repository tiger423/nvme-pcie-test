# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **Enterprise NVMe PCIe Gen5 SSD QA Test Framework** built for Python 3.12+ on Ubuntu 24.04. It's designed for comprehensive testing and monitoring of NVMe solid-state drives using nvme-cli tools.

The framework consists of:
- **Main QA suite** (`nvme-qa.py`) - Config-driven comprehensive testing
- **Interactive menu system** (`nvme-menu.py`) - User-friendly access to individual functions
- **Standalone samples** (`samples/`) - Individual, workable examples for each major function
- **Automated monitoring** (`scripts/`) - Background health monitoring with cron integration
- **Common utilities** (`utils/`) - Shared functionality across all components

## Primary Commands

### Running the Framework

```bash
# Interactive menu system (recommended for beginners)
python3 nvme-menu.py

# Full QA suite with configuration
python3 nvme-qa.py --config config.yaml --sudo

# Clone and basic setup
git clone https://github.com/tiger423/nvme-pcie-test
python3 nvme-qa.py --config config.yaml --sudo
```

### Individual Sample Usage

All samples support `--csv` flag for data export to `./csv_exports/`:

```bash
# Device discovery and listing
python3 samples/01_device_discovery.py --csv

# Device information with PCI details
python3 samples/02_device_info.py --device /dev/nvme0 --csv

# SMART health monitoring
python3 samples/03_smart_monitoring.py --namespace /dev/nvme0n1 --duration 60 --csv

# Critical health monitoring with automatic CSV export
python3 samples/04_health_csv_export.py --namespace /dev/nvme0n1 --continuous --interval 30

# FIO performance testing
python3 samples/05_fio_performance.py --target /dev/nvme0n1 --workload randread --csv

# Safe namespace formatting (requires confirmation)
sudo python3 samples/06_formatting.py --namespace /dev/nvme0n1 --lbaf 0
```

### Automated Health Monitoring

```bash
# Set up automated monitoring with cron
chmod +x scripts/setup_cron_monitoring.sh
./scripts/setup_cron_monitoring.sh

# Manual health checks
python3 scripts/automated_health_monitor.py --single
python3 scripts/automated_health_monitor.py --continuous

# Generate health reports
python3 scripts/automated_health_monitor.py --report 7
```

## Architecture Overview

### Core Components

- **`nvme-qa.py`**: Main framework with config-driven testing, supports JSON/HTML reports with embedded plots
- **`nvme-menu.py`**: Interactive CLI menu for accessing individual functions
- **`utils/common.py`**: Shared utilities including device discovery, command execution, ANSI sanitization
- **`utils/csv_export.py`**: CSV export functionality with automatic timestamping

### Key Architectural Patterns

1. **Config-driven approach**: All major operations configurable via YAML (`config.yaml`)
2. **Safety-first design**: Multiple confirmations for destructive operations, device validation
3. **Comprehensive error handling**: Graceful fallbacks, clear error messages, proper cleanup
4. **Output sanitization**: Global ANSI/CR/backspace cleanup for reliable parsing
5. **Privilege escalation**: Automatic sudo handling with `--sudo` re-exec option

### Device Discovery & Management

The framework uses **nvme-cli JSON output** (`nvme list -o json`) as the primary discovery mechanism:
- Controllers: `/dev/nvme0`, `/dev/nvme1`, etc.
- Namespaces: `/dev/nvme0n1`, `/dev/nvme1n1`, etc.
- PCI BDF resolution with fallbacks (hex-friendly path/uevent/udevadm)
- Safe `nvme list-subsys` wrapper with graceful fallbacks

### Data Export & Reporting

- **CSV exports**: Timestamped files in `./csv_exports/` with standardized formats
- **JSON/HTML reports**: Comprehensive reports with embedded matplotlib plots
- **Real-time monitoring**: Continuous health data collection with configurable intervals
- **Historical analysis**: Data retention and trend analysis capabilities

## Configuration

### Main Config (`config.yaml`)
- **Device selection**: Explicit lists, include/exclude regex patterns
- **Test parameters**: SMART monitoring duration/intervals, FIO workloads, filesystem options
- **Safety controls**: Format/sanitize enable flags, confirmation requirements
- **Output settings**: Report directories, export formats

### Monitoring Config (`configs/health_monitor.yaml`)
- **Alert thresholds**: Temperature, usage, media errors, critical warnings
- **Email notifications**: SMTP configuration for automated alerts  
- **Data retention**: CSV file retention periods
- **Monitoring intervals**: Frequency of health checks

## Dependencies & Requirements

- **Python 3.12+** (required)
- **nvme-cli tools** (required for device operations)
- **sudo access** (required for privileged operations)
- **fio** (optional, for performance testing)
- **PyYAML** (optional, graceful fallback if missing)
- **matplotlib** (for report generation with plots)

## Safety & Security Features

- **Destructive operation warnings**: Clear warnings for format/sanitize operations
- **Multi-level confirmations**: Required for dangerous operations
- **Device validation**: Ensures devices exist before operations
- **Privilege checks**: Verifies sudo access when needed
- **Safe operation cancellation**: Proper cleanup on interruption
- **No hardcoded credentials**: No secrets or keys in codebase