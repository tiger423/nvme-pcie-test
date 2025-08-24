# Setup Cron Monitoring Script - Detailed Explanation

## Overview

The `scripts/setup_cron_monitoring.sh` script is an interactive bash wizard that helps users set up automated NVMe health monitoring using cron jobs. It provides a user-friendly interface to configure scheduled monitoring without requiring deep knowledge of cron syntax.

## Script Architecture

### File Structure
```
scripts/setup_cron_monitoring.sh (94 lines)
├── Environment Setup (Lines 1-21)
├── User Interface (Lines 22-62)
├── Cron Job Creation (Lines 63-86)
└── Additional Options (Lines 87-94)
```

## Detailed Code Analysis

### 1. Environment Setup (Lines 1-21)

```bash
#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
MONITOR_SCRIPT="$SCRIPT_DIR/automated_health_monitor.py"
LOG_DIR="$PROJECT_DIR/logs"
```

**Purpose**: Establishes the script's runtime environment
- **SCRIPT_DIR**: Gets the absolute path of the scripts directory
- **PROJECT_DIR**: Gets the parent directory (nvme-pcie-test root)
- **MONITOR_SCRIPT**: Full path to the monitoring Python script
- **LOG_DIR**: Directory where monitoring logs will be stored

**Safety Checks**:
- Creates log directory if it doesn't exist (`mkdir -p "$LOG_DIR"`)
- Verifies the monitoring script exists before proceeding
- Makes the monitoring script executable (`chmod +x "$MONITOR_SCRIPT"`)

### 2. User Interface (Lines 22-62)

**Menu Display**:
```bash
echo "Available monitoring intervals:"
echo "1. Every 15 minutes"
echo "2. Every hour"
echo "3. Every 4 hours"
echo "4. Every 12 hours"
echo "5. Daily at 2 AM"
echo "6. Custom interval"
```

**Input Processing**:
Uses a `case` statement to convert user choices into cron schedule formats:

| Choice | Cron Schedule | Description |
|--------|---------------|-------------|
| 1 | `*/15 * * * *` | Every 15 minutes |
| 2 | `0 * * * *` | Every hour (at minute 0) |
| 3 | `0 */4 * * *` | Every 4 hours (at minute 0) |
| 4 | `0 */12 * * *` | Every 12 hours (at minute 0) |
| 5 | `0 2 * * *` | Daily at 2:00 AM |
| 6 | Custom input | User-defined cron schedule |

### 3. Cron Job Creation (Lines 63-86)

**Command Construction**:
```bash
CRON_COMMAND="cd $PROJECT_DIR && /usr/bin/python3 $MONITOR_SCRIPT --single >> $LOG_DIR/health_monitor.log 2>&1"
CRON_ENTRY="$CRON_SCHEDULE $CRON_COMMAND"
```

**Key Components**:
- **cd $PROJECT_DIR**: Ensures correct working directory
- **/usr/bin/python3**: Uses system Python (avoids PATH issues)
- **--single**: Runs one health check and exits
- **>> $LOG_DIR/health_monitor.log**: Appends output to log file
- **2>&1**: Redirects stderr to stdout for complete logging

**Cron Installation**:
```bash
(crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -
```
- Gets existing crontab entries
- Adds new monitoring entry
- Installs updated crontab

### 4. Additional Options (Lines 87-94)

Provides helpful commands for further setup:
- Configuration file creation
- Manual testing
- Report generation
- Continuous monitoring

## Flowchart

```
┌─────────────────────────────────────┐
│           START SCRIPT              │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│     Initialize Environment          │
│  • Set SCRIPT_DIR, PROJECT_DIR      │
│  • Set MONITOR_SCRIPT, LOG_DIR      │
│  • Create logs directory            │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│     Validate Prerequisites          │
│  • Check if monitor script exists   │
│  • Make monitor script executable   │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│      Display Menu Options           │
│  1. Every 15 minutes                │
│  2. Every hour                      │
│  3. Every 4 hours                   │
│  4. Every 12 hours                  │
│  5. Daily at 2 AM                   │
│  6. Custom interval                 │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│       Get User Choice               │
│     read -p "Select [1-6]: "        │
└─────────────┬───────────────────────┘
              │
              ▼
         ┌────────────┐
         │   Choice   │
         │   Valid?   │
         └─────┬──────┘
               │ No
               ▼
    ┌─────────────────┐
    │  Display Error  │
    │   Exit Script   │
    └─────────────────┘
               │ Yes
               ▼
┌─────────────────────────────────────┐
│      Convert to Cron Schedule       │
│                                     │
│  1 → */15 * * * *                   │
│  2 → 0 * * * *                      │
│  3 → 0 */4 * * *                    │
│  4 → 0 */12 * * *                   │
│  5 → 0 2 * * *                      │
│  6 → Custom input                   │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│     Build Cron Command              │
│  cd PROJECT_DIR &&                  │
│  /usr/bin/python3 MONITOR_SCRIPT    │
│  --single >> LOG_FILE 2>&1          │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│      Display Preview                │
│  • Show complete cron entry         │
│  • Show description of schedule     │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│      Confirm Installation           │
│   read -p "Add cron job? [y/N]: "   │
└─────────────┬───────────────────────┘
              │
              ▼
         ┌────────────┐
         │ Confirmed? │
         └─────┬──────┘
               │ No
               ▼
    ┌─────────────────┐
    │ "Cron job not   │
    │    added."      │
    └─────┬───────────┘
          │
          ▼
    ┌─────────────────┐
    │ Show Additional │
    │    Options      │
    └─────┬───────────┘
          │
          ▼
    ┌─────────────────┐
    │   END SCRIPT    │
    └─────────────────┘
               │ Yes
               ▼
┌─────────────────────────────────────┐
│       Install Cron Job              │
│  (crontab -l; echo CRON_ENTRY)      │
│         | crontab -               │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│      Success Messages               │
│  • "Cron job added successfully!"   │
│  • Show management commands         │
│  • Show test command                │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│     Show Additional Options         │
│  1. Create configuration file       │
│  2. Run single check                │
│  3. Generate health report          │
│  4. Start continuous monitoring     │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│           END SCRIPT                │
└─────────────────────────────────────┘
```

## Key Features Explained

### 1. **Path Resolution**
The script uses robust path resolution to work from any directory:
```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
```
This ensures the script can find its dependencies regardless of where it's executed from.

### 2. **Error Handling**
- Validates that the monitoring script exists before proceeding
- Provides clear error messages for invalid choices
- Uses safe cron installation that preserves existing entries

### 3. **Logging Strategy**
- All monitoring output goes to `logs/health_monitor.log`
- Uses append mode (`>>`) to preserve historical data
- Captures both stdout and stderr (`2>&1`)

### 4. **Cron Schedule Patterns**

| Pattern | Meaning | Use Case |
|---------|---------|----------|
| `*/15 * * * *` | Every 15 minutes | High-frequency monitoring |
| `0 * * * *` | Every hour | Standard monitoring |
| `0 */4 * * *` | Every 4 hours | Moderate monitoring |
| `0 */12 * * *` | Every 12 hours | Light monitoring |
| `0 2 * * *` | Daily at 2 AM | Minimal monitoring |

### 5. **Safety Features**
- **Preview before installation**: Shows exactly what will be added to crontab
- **Confirmation prompt**: Requires explicit user consent
- **Non-destructive**: Preserves existing cron jobs
- **Executable permissions**: Automatically makes scripts executable

## Usage Examples

### Basic Setup
```bash
./scripts/setup_cron_monitoring.sh
# Select option 2 (Every hour)
# Confirm with 'y'
```

### Custom Schedule
```bash
./scripts/setup_cron_monitoring.sh
# Select option 6 (Custom)
# Enter: "0 */6 * * *" (every 6 hours)
# Confirm with 'y'
```

### Verification
```bash
# Check installed cron jobs
crontab -l

# Monitor the logs
tail -f logs/health_monitor.log

# Test manually
cd /path/to/nvme-pcie-test
python3 scripts/automated_health_monitor.py --single
```

## Integration Points

### With Existing Menu System
- Uses the same `utils/common.py` utilities
- Leverages the fixed temperature conversion functions
- Outputs to the same CSV export directories

### With Monitoring Script
- Calls `automated_health_monitor.py --single`
- Uses the same configuration files
- Shares the same logging infrastructure

## Security Considerations

### File Permissions
- Script requires execute permissions on monitoring script
- Log directory must be writable by the user
- Cron jobs run with user's permissions (not root)

### Path Security
- Uses absolute paths to prevent PATH injection
- Validates script existence before installation
- Uses `/usr/bin/python3` to avoid PATH manipulation

## Troubleshooting

### Common Issues
1. **"Monitor script not found"**: Check that `automated_health_monitor.py` exists
2. **Permission denied**: Ensure log directory is writable
3. **Cron not running**: Check if cron service is active (`systemctl status cron`)
4. **No output in logs**: Verify cron job syntax with `crontab -l`

### Debug Commands
```bash
# Test the exact command that cron will run
cd /path/to/nvme-pcie-test && /usr/bin/python3 scripts/automated_health_monitor.py --single

# Check cron service status
systemctl status cron

# View cron logs
grep CRON /var/log/syslog
```

## Advanced Usage

### Multiple Monitoring Schedules
You can run the setup script multiple times to create different monitoring schedules:
- Frequent temperature checks (every 15 minutes)
- Daily comprehensive reports (daily at 2 AM)
- Weekly trend analysis (custom schedule)

### Custom Configuration
Create device-specific configurations:
```bash
# Create custom config
python3 scripts/automated_health_monitor.py --setup

# Edit for specific thresholds
nano configs/health_monitor.yaml

# Use custom config in cron
# Modify CRON_COMMAND to include: --config configs/custom.yaml
```

This script provides a robust, user-friendly way to set up automated NVMe health monitoring with minimal technical knowledge required from the user.
