clone:

git clone https://github.com/tiger423/nvme-pcie-test

run (ubunut 24.04, python 3.12):

python3 nvme-qa.py --config config.yaml --sudo


Highlights / Fixes:
- Robust "Device Info" (PCI BDF via sysfs/uevent/udevadm, hex bus/device supported).
- Safe `nvme list-subsys` wrapper (normalizes /dev path, fallbacks).
- Global command-output sanitizer (removes ANSI, applies backspaces, normalizes CR).
- Correct discovery (no bogus '/dev/nvme1n1n1').
- Explicit controller/namespace selection in config.
- fio_on_fs mode (file-based workloads on created/mounted FS).
- Power state sampling via 'nvme get-feature -f 2' during workloads.
- SMART trends, sensors, turbostat, nvme telemetry-log.
- JSON + HTML reports (embedded plots; escaped blocks).
- Plot fixes (ticks/ticklabels + series resampling).
- Privileged commands auto sudo-able; --sudo re-exec option.
- All string literals are raw (r"...") or raw+formatted (fr"...").

Usage:
  python3 nvme_qa.py --config config.yaml
  python3 nvme_qa.py --config config.yaml --sudo
  sudo -E python3 nvme_qa.py --config config.yaml


NVMe Gen5 QA Test Program — Developer & User Guide
What this tool does (at a glance)

Discovers NVMe controllers and their namespaces (or uses what you explicitly set).

Gathers device info (PCIe BDF, link speed/width, lspci -vv, nvme id-ctrl, list-subsys).

Optionally formats a namespace, creates & mounts a filesystem.

Runs SMART monitoring while executing fio workloads (raw or on filesystem).

Samples power feature (FID=2), lm-sensors, turbostat, and nvme telemetry-log in parallel.

Produces JSON + HTML reports (with embedded plots).

Works with Ubuntu 24.04 / Python 3.12; cmds requiring privileges auto-use sudo -n.



1) Flow chart & API cheat‑sheet
2) Flow chart (high-level run)
flowchart TD

  A[Start nvme_qa.py] --> B[Load config (JSON/YAML)]
  
  B --> C{--sudo flag?}
  
  C -->|yes & not root| D[Re-exec via sudo -E]
  
  C -->|no| E[List controllers]
  
  D --> E
  E -->|explicit in config?| F1[Use explicit controllers]
  E -->|else| F2[nvme list -o json -> derive controllers]
  F1 --> G[For each controller]
  F2 --> G

  subgraph Per-Controller Pipeline
    G --> H[Device Info\n(BDF via sysfs/uevent/udevadm)]
    H --> I[nvme list-subsys (robust)]
    I --> J[List namespaces (explicit or derived)]
    J --> K[Provision each namespace\n(format? mkfs? mount?)]
    K --> L[Monitor SMART (interval,duration)]
    L --> M[Run fio workloads (raw or on FS)]
    M --> N[Parallel telemetry: power(fid=2), sensors, turbostat]
    N --> O[Collect nvme telemetry-log]
    O --> P[Unmount (if mounted)]
  end

  P --> Q[Consolidate results -> JSON]
  Q --> R[Render HTML report]
  R --> S[End]

Key module-level helpers & APIs

All strings inside the code are raw strings (r"..." / fr"...").

Process/OS helpers

cmd_exists(name: str) -> bool
Check if a shell command exists on PATH.

run_cmd(cmd: str, require_root: bool=False) -> str
Run a shell command; auto sudo -n if require_root and not root.
(Global sanitizer removes ANSI, handles CR/backspaces, preserves final content.)

read_sysfs(path: str) -> Optional[str]
Read a sysfs file safely.

Config & I/O

load_config(path: Optional[str]) -> Dict[str, Any]
Load YAML/JSON (deep-merge with defaults).

save_json(data: dict, filepath: str) -> None
Save JSON with indent=2.

html_escape(s: str) -> str
Basic HTML escaping.

Discovery

list_all_namespaces() -> List[str]
Uses nvme list -o json → returns /dev/nvmeXnY list.

controller_from_ns(ns: str) -> str
/dev/nvmeXnY → /dev/nvmeX.

list_nvme_controllers(cfg) -> List[str]
Prefer controllers.explicit, else derive from all namespaces; apply include/exclude regex.

list_nvme_namespaces(ctrl, cfg) -> List[str]
Prefer namespaces.explicit, else derive for that controller.

Device info

_normalize_ctrl_path(ctrl: str) -> str
Ensure /dev/nvmeX path form.

_safe_nvme_list_subsys(ctrl: str) -> str
Tries nvme list-subsys -o json <ctrl>, normalize /dev, fallback to all subsystems.

get_pci_bdf_for_ctrl(ctrl: str) -> Optional[str]
Resolve PCI BDF using /sys/class/nvme/<name>/device (walk parents), uevent PCI_SLOT_NAME, and udevadm (handles hex bus/device).

get_device_info(ctrl: str) -> Dict[str, Any]
Returns { controller, pci_bdf, pcie_sysfs{speed/width}, lspci_vv, nvme_id_ctrl_json, nvme_list_subsys, nvme_list_json }.

Provisioning

nsid_from_path(ns: str) -> Optional[int]
Extract NSID from /dev/nvmeXnY.

format_namespace(ns: str, lbaf: int, ses: int, wait_after=5) -> str
nvme format on ns; if needed, fallback via controller -n NSID.

sanitize_controller(ctrl: str, action: str, ause: bool, owpass: int, interval: int, timeout: int) -> str
nvme sanitize + simple polling (log-id 0x81).

set_namespace_write_protect(ns: str, value: int) -> str
Feature FID 0x82 on NS.

create_filesystem(ns: str, fs_type: str, mkfs_options: str) -> str
mkfs.ext4/mkfs.xfs/… (raw target is the namespace device).

mount_namespace(ns: str, mount_base: str, mount_options: str) -> (mountpoint, output)
Creates <mount_base>/<nvmeXnY> and mounts.

unmount_path(mountpoint: str) -> str
umount <mp>.

Monitoring & workloads

get_nvme_health(ns: str) -> str
nvme smart-log -o json.

monitor_smart(ns, interval, duration) -> List[dict]
Samples SMART fields (temperature, percentage_used, media_errors, critical_warnings).

get_power_state_value(ctrl: str) -> Dict[str, Any]
nvme get-feature -f 2 -H parse current value.

power_monitor(ctrl, interval, duration) -> List[dict]

sensors_once() -> Any / sensors_monitor(interval,duration) -> List[Any]
From lm-sensors (sensors -j).

turbostat_run(duration, interval) -> str
CPU package/freq/power (requires linux-tools-*).

nvme_telemetry_log(ctrl: str) -> str
nvme telemetry-log -o json.

run_fio_test(target, rw, runtime, iodepth, bs, ioengine, on_fs=False, file_size=None) -> Dict[str,Any]
Runs fio against a raw device or a regular file (on filesystem). JSON output.

extract_fio_trends(fio_json) -> {"iops":[...], "latency":[...]}
Coarse trend extraction from fio job stats.

Plotting

plot_series(values, title, ylabel) -> <base64 png>

plot_smart_trend(logs, metric, ylabel) -> <base64 png>

plot_combined_timeline(smart_logs, fio_trends, workload) -> <base64 png>
(Resamples FIO trend to SMART timeline length; fixes tick label warnings.)

Per‑namespace/Per‑controller orchestration

test_workload(ns, rw, fio_cfg, tel_cfg, ctrl, fio_target=None, on_fs=False) -> dict
Runs one workload + all telemetry in parallel, returns fio json/trends and telemetry blobs.

test_namespace(ns, cfg, mountpoint=None) -> dict
SMART trend capture + parallel workloads (raw or on FS).

maybe_provision_namespace(ns, cfg) -> dict
Optional WP/format/mkfs/mount; returns mountpoint if mounted.

maybe_unmount_namespace(ns, cfg, provision_result) -> dict
Optional unmount on teardown.

Reporting & CLI

consolidate_results(controllers, cfg) -> (json_path, results_dict)
Runs the full per‑controller pipeline, saves JSON.

generate_html_report(results, cfg) -> html_path
Human‑readable report with embedded plots & escaped blocks.

main()
--config, --sudo handling, prints output locations.

2) config.yaml User Menu

All keys are optional (defaults apply). Recommended you explicitly set controllers.explicit and namespaces.explicit for predictable runs.

Top-level keys

output_dir (string): Where JSON/HTML reports are written.
Default: ./logs

Discovery filters
controllers:
  explicit: ["/dev/nvme1", "/dev/nvme2"]   # prefer explicit if provided
  include_regex: ".*"                      # regex applied to derived controllers
  exclude_regex: ""                        # regex to exclude derived controllers

namespaces:
  explicit: ["/dev/nvme1n1"]               # prefer explicit if provided
  include_regex: ".*"
  exclude_regex: ""

SMART sampling
smart:
  duration: 30     # seconds (per namespace test)
  interval: 5      # seconds

fio workloads
fio:
  runtime: 20              # seconds per workload
  iodepth: 4
  bs: "4k"
  ioengine: "io_uring"     # or "libaio"
  workloads: ["randread", "randwrite", "read", "write", "randrw"]

Filesystem & fio-on-FS
filesystem:
  create: true             # run mkfs.<type> on the namespace block device
  type: ext4               # ext4, xfs, ...
  mkfs_options: "-F"       # mkfs flags (e.g., ext4: -F, -E lazy_journal_tune=1)
  mount: true
  mount_base: /mnt/nvmeqa  # mountpoint becomes /mnt/nvmeqa/<nvmeXnY>
  mount_options: "defaults,noatime"
  fio_on_fs: true          # if true, fio targets files in the mounted FS
  fio_file_size: "8G"      # per-file size
  fio_file_prefix: "fio_nvmeqa"

Destructive ops (opt‑in!)
format:
  enabled: false           # if true: nvme format
  lbaf: 0                  # LBA format index
  ses: 0                   # Secure Erase Setting (0=none)

sanitize:
  enabled: false           # if true: nvme sanitize
  action: "none"           # "block" | "overwrite" | "crypto"
  ause: true               # Allow Unrestricted Sanitize Exit
  owpass: 1                # overwrite passes (if action=overwrite)
  interval: 5              # status poll interval (seconds)
  timeout: 1800            # stop waiting after N seconds

write_protect:
  enabled: false
  value: 1                 # FID 0x82 value (device-dependent)

Telemetry
telemetry:
  sensors_interval: 2      # lm-sensors sampling
  turbostat_interval: 2    # turbostat sampling
  nvme_telemetry: true     # nvme telemetry-log at end of controller run
  power_interval: 2        # nvme FID=2 sampling interval

3) Ready-to-use config examples
A) Minimal (your host: /dev/nvme1 + /dev/nvme1n1, fio_on_fs=true)
output_dir: ./nvme_reports

controllers:
  explicit: ["/dev/nvme1"]
  include_regex: ".*"
  exclude_regex: ""

namespaces:
  explicit: ["/dev/nvme1n1"]
  include_regex: ".*"
  exclude_regex: ""

smart:
  duration: 30
  interval: 5

fio:
  runtime: 20
  iodepth: 4
  bs: "4k"
  ioengine: "io_uring"
  workloads: ["randread", "randwrite"]

filesystem:
  create: true
  type: ext4
  mkfs_options: "-F"
  mount: true
  mount_base: /mnt/nvmeqa
  mount_options: "defaults,noatime"
  fio_on_fs: true
  fio_file_size: "8G"
  fio_file_prefix: "fio_nvmeqa"

telemetry:
  sensors_interval: 2
  turbostat_interval: 2
  nvme_telemetry: true
  power_interval: 2

B) Raw‑device workloads only (no mkfs/mount)
controllers:
  explicit: ["/dev/nvme1"]
namespaces:
  explicit: ["/dev/nvme1n1"]

filesystem:
  create: false
  mount: false
  fio_on_fs: false

fio:
  workloads: ["randread", "randwrite", "randrw"]

C) Multiple controllers/namespaces, with formatting (⚠️ destructive)
controllers:
  explicit: ["/dev/nvme0", "/dev/nvme1"]

namespaces:
  explicit: ["/dev/nvme0n1", "/dev/nvme1n1"]

format:
  enabled: true
  lbaf: 0
  ses: 0
  wait_after: 5

filesystem:
  create: true
  type: xfs
  mkfs_options: "-f"
  mount: true
  mount_base: /mnt/nvmeqa
  fio_on_fs: true
  fio_file_size: "16G"

fio:
  runtime: 30
  iodepth: 8
  bs: "4k"
  workloads: ["randread", "randwrite"]

D) Sanitize (⚠️ very destructive) + telemetry heavy
controllers:
  explicit: ["/dev/nvme1"]
namespaces:
  explicit: ["/dev/nvme1n1"]

sanitize:
  enabled: true
  action: "crypto"
  ause: true
  interval: 10
  timeout: 3600

telemetry:
  sensors_interval: 1
  turbostat_interval: 1
  nvme_telemetry: true
  power_interval: 1

4) Quick start
# deps
sudo apt-get update
sudo apt-get install -y nvme-cli fio lm-sensors linux-tools-common \
  linux-tools-$(uname -r) pciutils python3-pip
pip install matplotlib PyYAML

# run (explicit config)
sudo -E python3 nvme_qa.py --config config.yaml
# or allow auto-sudo reexec:
python3 nvme_qa.py --config config.yaml --sudo


Outputs

JSON: <output_dir>/ssd_report_<timestamp>.json

HTML: <output_dir>/ssd_report_<timestamp>.html

5) Tips & common fixes

Permission denied on nvme/mount/mkfs: use --sudo (script re-execs with sudo), or run under root.

“Invalid device name nvme1” in list-subsys: fixed by _safe_nvme_list_subsys; ensure your controllers.explicit includes /dev/ prefix.

Missing BDF: now robust (hex bus/device supported). If still unknown, check debug_udevadm_path in the HTML and share it.

Messy mkfs output: globally sanitized (ANSI/CR/backspaces removed).

Already has filesystem: If you don’t want to re‑mkfs, set filesystem.create: false and filesystem.mount: true (it’ll mount an existing FS).
