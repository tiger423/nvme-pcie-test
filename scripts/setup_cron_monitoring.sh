#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
MONITOR_SCRIPT="$SCRIPT_DIR/automated_health_monitor.py"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

echo "=== NVMe Health Monitoring Setup ==="
echo "Project directory: $PROJECT_DIR"
echo "Monitor script: $MONITOR_SCRIPT"
echo "Log directory: $LOG_DIR"

if [ ! -f "$MONITOR_SCRIPT" ]; then
    echo "Error: Monitor script not found at $MONITOR_SCRIPT"
    exit 1
fi

chmod +x "$MONITOR_SCRIPT"

echo ""
echo "Available monitoring intervals:"
echo "1. Every 15 minutes"
echo "2. Every hour"
echo "3. Every 4 hours"
echo "4. Every 12 hours"
echo "5. Daily at 2 AM"
echo "6. Custom interval"

read -p "Select monitoring interval [1-6]: " choice

case $choice in
    1)
        CRON_SCHEDULE="*/15 * * * *"
        DESCRIPTION="every 15 minutes"
        ;;
    2)
        CRON_SCHEDULE="0 * * * *"
        DESCRIPTION="every hour"
        ;;
    3)
        CRON_SCHEDULE="0 */4 * * *"
        DESCRIPTION="every 4 hours"
        ;;
    4)
        CRON_SCHEDULE="0 */12 * * *"
        DESCRIPTION="every 12 hours"
        ;;
    5)
        CRON_SCHEDULE="0 2 * * *"
        DESCRIPTION="daily at 2 AM"
        ;;
    6)
        read -p "Enter custom cron schedule (e.g., '0 */6 * * *'): " CRON_SCHEDULE
        DESCRIPTION="custom schedule: $CRON_SCHEDULE"
        ;;
    *)
        echo "Invalid choice. Exiting."
        exit 1
        ;;
esac

CRON_COMMAND="cd $PROJECT_DIR && /usr/bin/python3 $MONITOR_SCRIPT --single >> $LOG_DIR/health_monitor.log 2>&1"
CRON_ENTRY="$CRON_SCHEDULE $CRON_COMMAND"

echo ""
echo "Cron job to be added:"
echo "$CRON_ENTRY"
echo ""
echo "This will run NVMe health monitoring $DESCRIPTION"

read -p "Add this cron job? [y/N]: " confirm
if [[ $confirm =~ ^[Yy]$ ]]; then
    (crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -
    echo "Cron job added successfully!"
    echo ""
    echo "To view current cron jobs: crontab -l"
    echo "To remove this job later: crontab -e"
    echo "Monitor logs: tail -f $LOG_DIR/health_monitor.log"
    echo ""
    echo "Test the monitoring now:"
    echo "cd $PROJECT_DIR && python3 $MONITOR_SCRIPT --single"
else
    echo "Cron job not added."
fi

echo ""
echo "Additional setup options:"
echo "1. Create configuration file: python3 $MONITOR_SCRIPT --setup"
echo "2. Run single check: python3 $MONITOR_SCRIPT --single"
echo "3. Generate health report: python3 $MONITOR_SCRIPT --report 7"
echo "4. Start continuous monitoring: python3 $MONITOR_SCRIPT --continuous"
