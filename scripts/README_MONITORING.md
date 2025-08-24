# NVMe Automated Health Monitoring

This directory contains scripts for automated NVMe SSD health monitoring with CSV logging, alerts, and trend analysis.

## Quick Start

### 1. Set Up Automated Monitoring
```bash
# Make setup script executable
chmod +x scripts/setup_cron_monitoring.sh

# Run the setup wizard
./scripts/setup_cron_monitoring.sh
```

### 2. Create Configuration (Optional)
```bash
# Create sample configuration file
python3 scripts/automated_health_monitor.py --setup

# Edit the configuration
nano configs/health_monitor.yaml
```

### 3. Test Monitoring
```bash
# Run a single health check
python3 scripts/automated_health_monitor.py --single

# Generate a health report for the last 7 days
python3 scripts/automated_health_monitor.py --report 7
```

## Features

### 🔍 **Health Monitoring**
- **Temperature monitoring** with configurable thresholds
- **Drive wear tracking** (percentage used)
- **Media error detection** and trending
- **Critical warning alerts**
- **Power-on hours** and unsafe shutdown tracking

### 📊 **Data Logging**
- **CSV export** for all health metrics
- **Automatic file rotation** and retention
- **Historical trend analysis**
- **Per-device logging** with timestamps

### 🚨 **Alert System**
- **Configurable thresholds** for all metrics
- **Email notifications** (optional)
- **Multi-level alerts** (warning/critical)
- **Console logging** with timestamps

### ⏰ **Scheduling Options**
- **Cron integration** for automated monitoring
- **Flexible intervals** (15min, hourly, daily, custom)
- **Single-shot** or continuous monitoring modes
- **Background operation** with logging

## Usage Examples

### Manual Monitoring
```bash
# Single health check
python3 scripts/automated_health_monitor.py --single

# Continuous monitoring (Ctrl+C to stop)
python3 scripts/automated_health_monitor.py --continuous

# Health report for last 30 days
python3 scripts/automated_health_monitor.py --report 30
```

### Scheduled Monitoring
```bash
# Set up cron job (interactive wizard)
./scripts/setup_cron_monitoring.sh

# View monitoring logs
tail -f logs/health_monitor.log

# Check current cron jobs
crontab -l
```

### Configuration
```bash
# Create sample config
python3 scripts/automated_health_monitor.py --setup

# Use custom config
python3 scripts/automated_health_monitor.py --config configs/my_config.yaml --single
```

## Configuration Options

Edit `configs/health_monitor.yaml`:

```yaml
# Monitoring frequency (seconds)
monitoring_interval: 3600  # 1 hour

# Data retention
csv_retention_days: 30

# Email alerts
email_alerts: true
email_config:
  smtp_server: "smtp.gmail.com"
  smtp_port: 587
  sender_email: "monitoring@company.com"
  sender_password: "app-password"
  recipient_email: "admin@company.com"

# Alert thresholds
alert_thresholds:
  temperature_warning: 70      # °C
  temperature_critical: 80     # °C
  percentage_used_warning: 80  # %
  percentage_used_critical: 90 # %
  media_errors_warning: 50
  media_errors_critical: 100
```

## Output Files

### CSV Data Files
- **Location**: `csv_exports/automated_monitoring/`
- **Format**: `health_monitor_dev_nvme0n1.csv`
- **Contents**: Timestamp, device, temperature, usage, errors, warnings

### Log Files
- **Location**: `logs/health_monitor.log`
- **Contents**: Monitoring events, alerts, errors
- **Rotation**: Automatic (configurable)

## Alert Thresholds

### Temperature
- **Warning**: 70°C (configurable)
- **Critical**: 80°C (configurable)
- **Action**: Monitor cooling, check workload

### Drive Usage
- **Warning**: 80% (configurable)
- **Critical**: 90% (configurable)
- **Action**: Plan drive replacement

### Media Errors
- **Warning**: 50 errors (configurable)
- **Critical**: 100 errors (configurable)
- **Action**: Backup data, monitor closely

### Critical Warnings
- **Any non-zero value**: Immediate alert
- **Action**: Check drive status, consider replacement

## Integration with Existing Menu

The automated monitoring works alongside your existing NVMe menu system:

- **Option 3**: Manual SMART monitoring (immediate results)
- **Option 4**: Manual CSV export (one-time export)
- **Automated script**: Scheduled monitoring with alerts

## Troubleshooting

### Common Issues

1. **Permission errors**: Run with `sudo` if needed
2. **No devices found**: Check NVMe device availability
3. **Email alerts not working**: Verify SMTP configuration
4. **CSV files not created**: Check directory permissions

### Debug Commands
```bash
# Test device detection
python3 -c "from utils.common import list_nvme_devices_nvme_cli; print(list_nvme_devices_nvme_cli())"

# Test SMART data retrieval
python3 -c "from utils.common import get_nvme_health; print(get_nvme_health('/dev/nvme0n1'))"

# Check cron job status
systemctl status cron
grep CRON /var/log/syslog
```

## Advanced Usage

### Custom Thresholds
Create device-specific configurations for different drive types or usage patterns.

### Integration with Monitoring Systems
Export CSV data to Grafana, Prometheus, or other monitoring platforms.

### Predictive Analysis
Use historical CSV data to predict drive failure or maintenance windows.

### Multi-Server Deployment
Deploy across multiple servers with centralized alerting.
