#!/usr/bin/env python3
"""
Automated NVMe Health Monitoring Script
Runs scheduled SMART checks, logs data to CSV, and provides alerts
"""

import sys
import json
import time
import argparse
import smtplib
from pathlib import Path
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.common import (print_header, list_nvme_devices_nvme_cli, 
                         get_nvme_health, timestamp, get_temperature_celsius)
from utils.csv_export import save_health_data_csv, get_csv_filepath, append_to_csv

class HealthThresholds:
    """Define health thresholds for alerts"""
    TEMPERATURE_WARNING = 70  # °C
    TEMPERATURE_CRITICAL = 80  # °C
    PERCENTAGE_USED_WARNING = 80  # %
    PERCENTAGE_USED_CRITICAL = 90  # %
    MEDIA_ERRORS_WARNING = 50
    MEDIA_ERRORS_CRITICAL = 100
    CRITICAL_WARNINGS_ANY = 1  # Any non-zero value

class NVMeHealthMonitor:
    def __init__(self, config_file=None):
        self.config = self.load_config(config_file)
        self.csv_base_path = Path("csv_exports/automated_monitoring")
        self.csv_base_path.mkdir(parents=True, exist_ok=True)
        
    def load_config(self, config_file):
        """Load monitoring configuration"""
        default_config = {
            "monitoring_interval": 3600,  # 1 hour in seconds
            "csv_retention_days": 30,
            "email_alerts": False,
            "email_config": {
                "smtp_server": "smtp.gmail.com",
                "smtp_port": 587,
                "sender_email": "",
                "sender_password": "",
                "recipient_email": ""
            },
            "alert_thresholds": {
                "temperature_warning": 70,
                "temperature_critical": 80,
                "percentage_used_warning": 80,
                "percentage_used_critical": 90,
                "media_errors_warning": 50,
                "media_errors_critical": 100
            }
        }
        
        if config_file and Path(config_file).exists():
            try:
                import yaml
                with open(config_file, 'r') as f:
                    user_config = yaml.safe_load(f)
                default_config.update(user_config)
            except ImportError:
                print("Warning: PyYAML not installed, using default config")
            except Exception as e:
                print(f"Warning: Could not load config file: {e}")
        
        return default_config
    
    def get_device_health(self, namespace):
        """Get health data for a single device"""
        try:
            raw_health = get_nvme_health(namespace)
            if raw_health.startswith("Error:"):
                return None, raw_health
            
            health_data = json.loads(raw_health)
            
            health_metrics = {
                "timestamp": datetime.now().isoformat(),
                "namespace": namespace,
                "temperature": get_temperature_celsius(health_data),
                "percentage_used": health_data.get("percentage_used", 0),
                "media_errors": health_data.get("media_errors", 0),
                "critical_warnings": health_data.get("critical_warning", 0),
                "power_on_hours": health_data.get("power_on_hours", 0),
                "unsafe_shutdowns": health_data.get("unsafe_shutdowns", 0),
                "data_units_read": health_data.get("data_units_read", 0),
                "data_units_written": health_data.get("data_units_written", 0)
            }
            
            return health_metrics, None
            
        except json.JSONDecodeError as e:
            return None, f"JSON decode error: {e}"
        except Exception as e:
            return None, f"Unexpected error: {e}"
    
    def check_health_alerts(self, health_metrics):
        """Check if health metrics exceed alert thresholds"""
        alerts = []
        thresholds = self.config["alert_thresholds"]
        
        temp = health_metrics["temperature"]
        if temp >= thresholds["temperature_critical"]:
            alerts.append(f"CRITICAL: Temperature {temp:.1f}°C exceeds critical threshold ({thresholds['temperature_critical']}°C)")
        elif temp >= thresholds["temperature_warning"]:
            alerts.append(f"WARNING: Temperature {temp:.1f}°C exceeds warning threshold ({thresholds['temperature_warning']}°C)")
        
        used = health_metrics["percentage_used"]
        if used >= thresholds["percentage_used_critical"]:
            alerts.append(f"CRITICAL: Drive usage {used}% exceeds critical threshold ({thresholds['percentage_used_critical']}%)")
        elif used >= thresholds["percentage_used_warning"]:
            alerts.append(f"WARNING: Drive usage {used}% exceeds warning threshold ({thresholds['percentage_used_warning']}%)")
        
        errors = health_metrics["media_errors"]
        if errors >= thresholds["media_errors_critical"]:
            alerts.append(f"CRITICAL: Media errors {errors} exceed critical threshold ({thresholds['media_errors_critical']})")
        elif errors >= thresholds["media_errors_warning"]:
            alerts.append(f"WARNING: Media errors {errors} exceed warning threshold ({thresholds['media_errors_warning']})")
        
        if health_metrics["critical_warnings"] > 0:
            alerts.append(f"CRITICAL: Drive reports critical warning flags: {health_metrics['critical_warnings']}")
        
        return alerts
    
    def send_email_alert(self, subject, body):
        """Send email alert if configured"""
        if not self.config["email_alerts"]:
            return False
        
        email_config = self.config["email_config"]
        if not all([email_config["sender_email"], email_config["sender_password"], email_config["recipient_email"]]):
            print("Warning: Email alerts enabled but configuration incomplete")
            return False
        
        try:
            msg = MIMEMultipart()
            msg['From'] = email_config["sender_email"]
            msg['To'] = email_config["recipient_email"]
            msg['Subject'] = subject
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(email_config["smtp_server"], email_config["smtp_port"])
            server.starttls()
            server.login(email_config["sender_email"], email_config["sender_password"])
            text = msg.as_string()
            server.sendmail(email_config["sender_email"], email_config["recipient_email"], text)
            server.quit()
            
            return True
        except Exception as e:
            print(f"Failed to send email alert: {e}")
            return False
    
    def log_to_csv(self, health_metrics):
        """Log health metrics to CSV file"""
        csv_filename = f"health_monitor_{health_metrics['namespace'].replace('/', '_')}.csv"
        csv_path = self.csv_base_path / csv_filename
        
        fieldnames = ['timestamp', 'namespace', 'temperature', 'percentage_used', 
                     'media_errors', 'critical_warnings', 'power_on_hours', 
                     'unsafe_shutdowns', 'data_units_read', 'data_units_written']
        
        result = append_to_csv(health_metrics, str(csv_path), fieldnames)
        return result
    
    def monitor_single_check(self):
        """Perform a single monitoring check on all devices"""
        controllers, namespaces = list_nvme_devices_nvme_cli()
        
        if not namespaces:
            print("No NVMe namespaces found for monitoring")
            return
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Monitoring {len(namespaces)} NVMe device(s)")
        
        all_alerts = []
        
        for namespace in namespaces:
            health_metrics, error = self.get_device_health(namespace)
            
            if error:
                print(f"Error monitoring {namespace}: {error}")
                continue
            
            csv_result = self.log_to_csv(health_metrics)
            print(f"  {namespace}: T={health_metrics['temperature']:.1f}°C, "
                  f"Used={health_metrics['percentage_used']}%, "
                  f"Errors={health_metrics['media_errors']}")
            
            alerts = self.check_health_alerts(health_metrics)
            if alerts:
                all_alerts.extend([f"{namespace}: {alert}" for alert in alerts])
        
        if all_alerts:
            alert_subject = f"NVMe Health Alert - {len(all_alerts)} issue(s) detected"
            alert_body = "NVMe Health Monitoring Alert\n\n" + "\n".join(all_alerts)
            
            print("\n*** HEALTH ALERTS ***")
            for alert in all_alerts:
                print(f"  {alert}")
            
            if self.send_email_alert(alert_subject, alert_body):
                print("Email alert sent successfully")
    
    def monitor_continuous(self):
        """Run continuous monitoring with configured interval"""
        interval = self.config["monitoring_interval"]
        print(f"Starting continuous NVMe health monitoring (interval: {interval}s)")
        print("Press Ctrl+C to stop")
        
        try:
            while True:
                self.monitor_single_check()
                print(f"Next check in {interval} seconds...\n")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nMonitoring stopped by user")
    
    def generate_health_report(self, days=7):
        """Generate a health report from recent CSV data"""
        print(f"Generating health report for last {days} days...")
        
        controllers, namespaces = list_nvme_devices_nvme_cli()
        if not namespaces:
            print("No NVMe namespaces found")
            return
        
        for namespace in namespaces:
            csv_filename = f"health_monitor_{namespace.replace('/', '_')}.csv"
            csv_path = self.csv_base_path / csv_filename
            
            if not csv_path.exists():
                print(f"No monitoring data found for {namespace}")
                continue
            
            print(f"\n--- Health Report: {namespace} ---")
            
            try:
                import csv
                recent_data = []
                cutoff_date = datetime.now() - timedelta(days=days)
                
                with open(csv_path, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            row_date = datetime.fromisoformat(row['timestamp'])
                            if row_date >= cutoff_date:
                                recent_data.append(row)
                        except ValueError:
                            continue
                
                if not recent_data:
                    print(f"No recent data (last {days} days)")
                    continue
                
                temps = [float(row['temperature']) for row in recent_data if row['temperature']]
                used_vals = [float(row['percentage_used']) for row in recent_data if row['percentage_used']]
                
                print(f"Data points: {len(recent_data)}")
                if temps:
                    print(f"Temperature: Min={min(temps):.1f}°C, Max={max(temps):.1f}°C, Avg={sum(temps)/len(temps):.1f}°C")
                if used_vals:
                    print(f"Usage: Current={used_vals[-1]:.1f}%, Change={used_vals[-1]-used_vals[0]:.2f}%")
                
                latest = recent_data[-1]
                print(f"Latest media errors: {latest['media_errors']}")
                print(f"Latest critical warnings: {latest['critical_warnings']}")
                
            except Exception as e:
                print(f"Error reading CSV data: {e}")

def main():
    parser = argparse.ArgumentParser(description="Automated NVMe Health Monitoring")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--single", action="store_true", help="Run single check and exit")
    parser.add_argument("--continuous", action="store_true", help="Run continuous monitoring")
    parser.add_argument("--report", type=int, metavar="DAYS", help="Generate health report for last N days")
    parser.add_argument("--setup", action="store_true", help="Create sample configuration file")
    
    args = parser.parse_args()
    
    if args.setup:
        create_sample_config()
        return
    
    monitor = NVMeHealthMonitor(args.config)
    
    if args.single:
        monitor.monitor_single_check()
    elif args.continuous:
        monitor.monitor_continuous()
    elif args.report:
        monitor.generate_health_report(args.report)
    else:
        print("Please specify --single, --continuous, --report N, or --setup")
        print("Use --help for more information")

def create_sample_config():
    """Create a sample configuration file"""
    config_content = """# NVMe Health Monitoring Configuration

monitoring_interval: 3600

csv_retention_days: 30

email_alerts: false
email_config:
  smtp_server: "smtp.gmail.com"
  smtp_port: 587
  sender_email: "your-email@gmail.com"
  sender_password: "your-app-password"
  recipient_email: "alerts@your-domain.com"

alert_thresholds:
  temperature_warning: 70      # °C
  temperature_critical: 80     # °C
  percentage_used_warning: 80  # %
  percentage_used_critical: 90 # %
  media_errors_warning: 50
  media_errors_critical: 100
"""
    
    config_path = Path("configs/health_monitor.yaml")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(config_path, 'w') as f:
        f.write(config_content)
    
    print(f"Sample configuration created: {config_path}")
    print("Edit this file to customize your monitoring settings")

if __name__ == "__main__":
    main()
