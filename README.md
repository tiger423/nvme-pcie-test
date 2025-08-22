Awesome — I’ve added everything you asked for:

Write‑protect & secure‑erase hooks (NVMe format/sanitize, optional Namespace Write Protect feature).

Namespace‑specific format + filesystem provisioning (mkfs + mount/unmount).

Per‑workload CPU & power telemetry using sensors, turbostat, plus NVMe telemetry‑log.

Still: multi‑controller, multi‑namespace, parallel workloads, SMART/FIO charts, combined timelines, config‑driven.

Below is the complete, ready‑to‑run script (nvme_qa.py) and an updated requirements.txt plus sample config.

requirements.txt
matplotlib==3.9.2
PyYAML==6.0.2

System packages to install (Ubuntu 24.04)

sudo apt update
sudo apt install -y nvme-cli fio lm-sensors linux-tools-common pciutils \
    e2fsprogs xfsprogs btrfs-progs util-linux

# turbostat is in linux-tools-$(uname -r); install matching kernel tools:
sudo apt install -y "linux-tools-$(uname -r)"

Then:

pip install -r requirements.txt


Example config.yaml (covers all new features)

output_dir: ./nvme_reports

smart:
  duration: 60
  interval: 10

fio:
  runtime: 60
  iodepth: 16
  bs: 4k
  ioengine: io_uring
  workloads: [randread, randwrite, read, write, randrw]

controllers:
  include_regex: ".*"
  exclude_regex: ""

namespaces:
  include_regex: ".*"
  exclude_regex: ""

sanitize:
  enabled: false          # set true to sanitize each controller before tests
  action: "crypto"        # none | block | overwrite | crypto
  ause: true
  owpass: 1
  interval: 5
  timeout: 1800

format:
  enabled: false          # set true to format namespaces before tests
  lbaf: 0
  ses: 0                  # 0 none, 1 user-data erase, 2 crypto erase
  wait_after: 5

write_protect:
  enabled: false          # requires NVMe feature 0x82 support
  value: 1                # 0 disable, 1 enable (device-specific semantics)

filesystem:
  create: false           # set true to mkfs per namespace (BEFORE tests)
  type: ext4
  mkfs_options: "-F"
  mount: false            # set true to mount after mkfs
  mount_base: "/mnt/nvmeqa"
  mount_options: "defaults,noatime"

telemetry:
  sensors_interval: 2
  turbostat_interval: 2
  nvme_telemetry: true


Notes & caveats

Write Protect (Feature 0x82) is optional in NVMe. If unsupported, you’ll see an error captured in the report — that’s expected.

Sanitize vs Format: sanitize is controller‑wide destructive action; format acts at the namespace (we attempt ns path; fall back to controller + NSID).

Filesystem + fio: this script runs fio on raw namespaces. If you enable filesystem.create + mount, you’re provisioning for later use — fio here doesn’t target the mounted FS file (by design). If you want fio-on-filesystem, I can add a fio_on_fs: true mode that writes test files under the mountpoints.

turbostat output is kept raw (varies by platform). It’s placed under each workload section in the HTML (collapsible).

Root privileges: sanitize/format/mkfs/mount/umount/turbostat will usually need sudo. The script tries sudo -n (non‑interactive). If you don’t have NOPASSWD configured, run the script with sudo or adjust sudoers.



