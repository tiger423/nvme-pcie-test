#!/usr/bin/env python3
"""
NVMe Report Generation Sample
Generate HTML reports with embedded plots and visualizations
"""

import sys
import json
import os
import base64
import io
from pathlib import Path
import argparse

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.common import print_header, print_section, timestamp

try:
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use('Agg')
    HAVE_MATPLOTLIB = True
except ImportError:
    HAVE_MATPLOTLIB = False
    print("⚠️  matplotlib not available. Install with: pip install matplotlib")

def create_sample_data():
    import time
    import random
    
    sample_smart_logs = []
    sample_fio_data = {"iops": [], "latency": []}
    
    for i in range(20):
        sample_smart_logs.append({
            "time": f"{12 + i//4:02d}:{(i*3)%60:02d}:{(i*7)%60:02d}",
            "temperature": 45 + random.randint(-5, 15),
            "percentage_used": 2 + i * 0.1,
            "media_errors": random.randint(0, 2),
            "critical_warnings": 0
        })
        
        sample_fio_data["iops"].append(45000 + random.randint(-5000, 10000))
        sample_fio_data["latency"].append(80 + random.randint(-20, 40))
    
    return sample_smart_logs, sample_fio_data

def b64_plot(fig):
    if not HAVE_MATPLOTLIB:
        return ""
    
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode('utf-8')
    buf.close()
    plt.close(fig)
    return img_b64

def plot_smart_trend(logs, metric, ylabel):
    if not HAVE_MATPLOTLIB or not logs:
        return ""
    
    times = [e["time"] for e in logs]
    values = [e.get(metric, 0) for e in logs]
    
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(range(len(times)), values, marker='o', linewidth=2, markersize=4)
    ax.set_xlabel("Time")
    ax.set_ylabel(ylabel)
    ax.set_title(f"SMART {metric.replace('_', ' ').title()} Trend")
    ax.grid(True, alpha=0.3)
    
    step = max(1, len(times) // 10)
    ax.set_xticks(range(0, len(times), step))
    ax.set_xticklabels([times[i] for i in range(0, len(times), step)], rotation=45)
    
    fig.tight_layout()
    return b64_plot(fig)

def plot_performance_trend(data, metric, ylabel):
    if not HAVE_MATPLOTLIB or not data:
        return ""
    
    values = data.get(metric, [])
    if not values:
        return ""
    
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(range(len(values)), values, marker='s', linewidth=2, markersize=4, color='green')
    ax.set_xlabel("Sample")
    ax.set_ylabel(ylabel)
    ax.set_title(f"FIO {metric.upper()} Trend")
    ax.grid(True, alpha=0.3)
    
    fig.tight_layout()
    return b64_plot(fig)

def plot_combined_timeline(smart_logs, fio_data, workload):
    if not HAVE_MATPLOTLIB or not smart_logs:
        return ""
    
    times = [e["time"] for e in smart_logs]
    temps = [e.get("temperature", 0) for e in smart_logs]
    x = list(range(len(times)))
    
    iops_series = fio_data.get("iops", [])
    if len(iops_series) != len(times):
        iops_series = iops_series[:len(times)] + [0] * (len(times) - len(iops_series))
    
    fig, ax1 = plt.subplots(figsize=(12, 6))
    ax1.set_xlabel("Time")
    ax1.set_ylabel("Temperature (°C)", color="tab:red")
    ax1.plot(x, temps, marker="o", color="tab:red", label="Temperature")
    ax1.tick_params(axis="y", labelcolor="tab:red")
    
    ax2 = ax1.twinx()
    ax2.set_ylabel("IOPS", color="tab:blue")
    ax2.plot(x, iops_series, marker="s", color="tab:blue", label="IOPS")
    ax2.tick_params(axis="y", labelcolor="tab:blue")
    
    ax1.set_title(f"Combined Timeline - {workload}")
    ax1.grid(True, alpha=0.3)
    
    step = max(1, len(times) // 8)
    ax1.set_xticks(range(0, len(times), step))
    ax1.set_xticklabels([times[i] for i in range(0, len(times), step)], rotation=45)
    
    fig.tight_layout()
    return b64_plot(fig)

def html_escape(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def generate_sample_html_report(output_file):
    print_header("Generating Sample HTML Report")
    
    smart_logs, fio_data = create_sample_data()
    
    html = [
        "<html><head><meta charset='utf-8'><title>NVMe SSD Sample Report</title>",
        "<style>",
        "body { font-family: Arial, sans-serif; margin: 20px; }",
        "h1, h2, h3 { color: #333; }",
        "details { margin: 10px 0; }",
        "summary { cursor: pointer; font-weight: bold; }",
        "pre { background: #f5f5f5; padding: 10px; border-radius: 5px; overflow-x: auto; }",
        "img { max-width: 100%; height: auto; margin: 10px 0; }",
        ".warning { color: #ff6600; }",
        ".success { color: #00aa00; }",
        "</style>",
        "</head><body>",
        "<h1>Enterprise NVMe PCIe Gen5 SSD Sample Report</h1>",
        f"<p>Generated: {timestamp()}</p>",
        "<hr>"
    ]
    
    html.append("<h2>Controller: /dev/nvme0 (Sample Data)</h2>")
    
    device_info = {
        "controller": "/dev/nvme0",
        "model": "Samsung 980 PRO 2TB",
        "serial": "S1234567890",
        "firmware": "1B2QEXM7",
        "pci_bdf": "0000:01:00.0"
    }
    
    html.append("<h3>Device Information</h3>")
    html.append(f"<pre>{html_escape(json.dumps(device_info, indent=2))}</pre>")
    
    html.append("<h3>Namespace: /dev/nvme0n1</h3>")
    
    if smart_logs:
        html.append("<h4>SMART Trends</h4>")
        
        for metric, ylabel in [("temperature", "Temp (°C)"),
                               ("percentage_used", "% Used"),
                               ("media_errors", "Media Errors")]:
            b64 = plot_smart_trend(smart_logs, metric, ylabel)
            if b64:
                html.append(f"<p><strong>{metric.replace('_', ' ').title()}</strong></p>")
                html.append(f"<img src='data:image/png;base64,{b64}'/>")
    
    html.append("<h4>Workload: randread (sample data)</h4>")
    html.append("<p><b>Target:</b> /dev/nvme0n1</p>")
    
    iops_plot = plot_performance_trend(fio_data, "iops", "IOPS")
    if iops_plot:
        html.append("<p><strong>IOPS Trend</strong></p>")
        html.append(f"<img src='data:image/png;base64,{iops_plot}'/>")
    
    latency_plot = plot_performance_trend(fio_data, "latency", "Latency (μs)")
    if latency_plot:
        html.append("<p><strong>Latency Trend</strong></p>")
        html.append(f"<img src='data:image/png;base64,{latency_plot}'/>")
    
    combined_plot = plot_combined_timeline(smart_logs, fio_data, "randread")
    if combined_plot:
        html.append("<h4>Combined Timeline (randread)</h4>")
        html.append(f"<img src='data:image/png;base64,{combined_plot}'/>")
    
    sample_telemetry = {
        "power_states": [0, 0, 1, 0, 0],
        "sensors_series": "Temperature data collected",
        "turbostat": "CPU utilization and power state data..."
    }
    
    html.append("<details><summary>Sample Telemetry Data</summary><pre>")
    html.append(html_escape(json.dumps(sample_telemetry, indent=2)))
    html.append("</pre></details>")
    
    html.append("<hr>")
    html.append("<p><em>This is a sample report generated with synthetic data for demonstration purposes.</em></p>")
    html.append("</body></html>")
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("".join(html))
    
    return output_file

def generate_html_from_json(json_file, output_file):
    print_header(f"Generating HTML Report from {json_file}")
    
    try:
        with open(json_file, 'r') as f:
            results = json.load(f)
    except Exception as e:
        print(f"❌ Error reading JSON file: {e}")
        return None
    
    html = [
        "<html><head><meta charset='utf-8'><title>NVMe SSD Report</title>",
        "<style>",
        "body { font-family: Arial, sans-serif; margin: 20px; }",
        "h1, h2, h3 { color: #333; }",
        "details { margin: 10px 0; }",
        "summary { cursor: pointer; font-weight: bold; }",
        "pre { background: #f5f5f5; padding: 10px; border-radius: 5px; overflow-x: auto; }",
        "img { max-width: 100%; height: auto; margin: 10px 0; }",
        "</style>",
        "</head><body>",
        "<h1>Enterprise NVMe PCIe Gen5 SSD Report</h1>",
        f"<p>Generated: {timestamp()}</p>",
        "<hr>"
    ]
    
    for ctrl, data in results.items():
        html.append(f"<h2>Controller: {ctrl}</h2>")
        
        if "info" in data:
            info_pretty = html_escape(json.dumps(data["info"], indent=2))
            html.append(f"<h3>Device Info</h3><pre>{info_pretty}</pre>")
        
        for ns, ns_obj in data.get("namespaces", {}).items():
            html.append(f"<h3>Namespace: {ns}</h3>")
            
            res = ns_obj.get("results", {})
            logs = res.get("smart_logs", [])
            
            if logs:
                html.append("<h4>SMART Data</h4>")
                html.append(f"<p>Collected {len(logs)} SMART readings</p>")
                
                for metric, ylabel in [("temperature", "Temp (°C)"),
                                       ("percentage_used", "% Used"),
                                       ("media_errors", "Media Errors")]:
                    b64 = plot_smart_trend(logs, metric, ylabel)
                    if b64:
                        html.append(f"<p><strong>{metric.replace('_', ' ').title()}</strong></p>")
                        html.append(f"<img src='data:image/png;base64,{b64}'/>")
            
            workloads = res.get("workloads", {})
            for rw, wdata in workloads.items():
                html.append(f"<h4>Workload: {rw}</h4>")
                if "fio_trends" in wdata:
                    fio_trends = wdata["fio_trends"]
                    
                    iops_plot = plot_performance_trend(fio_trends, "iops", "IOPS")
                    if iops_plot:
                        html.append("<p><strong>IOPS</strong></p>")
                        html.append(f"<img src='data:image/png;base64,{iops_plot}'/>")
                    
                    latency_plot = plot_performance_trend(fio_trends, "latency", "Latency (μs)")
                    if latency_plot:
                        html.append("<p><strong>Latency</strong></p>")
                        html.append(f"<img src='data:image/png;base64,{latency_plot}'/>")
        
        html.append("<hr>")
    
    html.append("</body></html>")
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("".join(html))
    
    return output_file

def main():
    parser = argparse.ArgumentParser(description="NVMe Report Generation")
    parser.add_argument("--json-input", help="Input JSON file from nvme-qa.py")
    parser.add_argument("--output", help="Output HTML file")
    parser.add_argument("--sample", action="store_true", help="Generate sample report with synthetic data")
    args = parser.parse_args()
    
    if not HAVE_MATPLOTLIB:
        print("❌ matplotlib is required for report generation")
        print("Install with: pip install matplotlib")
        return
    
    output_file = args.output or f"nvme_report_{timestamp()}.html"
    
    if args.sample:
        result_file = generate_sample_html_report(output_file)
        if result_file:
            print(f"✅ Sample HTML report generated: {result_file}")
            print(f"Open in browser: file://{os.path.abspath(result_file)}")
    elif args.json_input:
        if not os.path.exists(args.json_input):
            print(f"❌ JSON input file not found: {args.json_input}")
            return
        
        result_file = generate_html_from_json(args.json_input, output_file)
        if result_file:
            print(f"✅ HTML report generated: {result_file}")
            print(f"Open in browser: file://{os.path.abspath(result_file)}")
    else:
        print("Please specify either --sample or --json-input")
        print("Examples:")
        print("  python3 11_report_generation.py --sample")
        print("  python3 11_report_generation.py --json-input results.json --output report.html")

if __name__ == "__main__":
    main()
