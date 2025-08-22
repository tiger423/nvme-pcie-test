requirements.txt
matplotlib==3.9.2
PyYAML==6.0.2

Minimal quick‑start

Install system packages:

sudo apt update
sudo apt install -y nvme-cli fio lm-sensors linux-tools-common "linux-tools-$(uname -r)" \
  pciutils e2fsprogs xfsprogs btrfs-progs util-linux


Install Python deps:

pip install -r requirements.txt


Save this config.yaml (enables filesystem provisioning + fio_on_fs + power sampling):

output_dir: ./nvme_reports

smart:
  duration: 45
  interval: 5

fio:
  runtime: 45
  iodepth: 8
  bs: 4k
  ioengine: io_uring
  workloads: [randread, randwrite]

controllers:
  include_regex: ".*"
  exclude_regex: ""

namespaces:
  include_regex: ".*"
  exclude_regex: ""

# optional destructive ops (off by default)
sanitize: { enabled: false, action: "none" }
format:   { enabled: false, lbaf: 0, ses: 0 }

write_protect: { enabled: false, value: 1 }

filesystem:
  create: true          # mkfs the namespace
  type: ext4
  mkfs_options: "-F"
  mount: true           # mount it
  mount_base: "/mnt/nvmeqa"
  mount_options: "defaults,noatime"
  fio_on_fs: true       # run fio on a file under the mountpoint
  fio_file_size: "8G"
  fio_file_prefix: "fio_nvmeqa"

telemetry:
  sensors_interval: 2
  turbostat_interval: 2
  nvme_telemetry: true
  power_interval: 2


Run:

python nvme_qa.py --config config.yaml


Outputs:

JSON: ./nvme_reports/ssd_report_<timestamp>.json

HTML: ./nvme_reports/ssd_report_<timestamp>.html (open in browser)

Shows per‑namespace SMART trends, per‑workload IOPS/Latency, combined timeline, and telemetry (incl. power states).
