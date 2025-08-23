
git clone https://github/tiger423/nvme-pcie-test


What’s fixed / added

✅ Correct discovery logic

New list_nvme_controllers() derives unique /dev/nvmeX controllers from nvme list -o json.

list_nvme_namespaces(ctrl) now filters the global list by controller prefix, no more appending n1.

✅ Explicit selection (config)

controllers.explicit: list of controllers (e.g., /dev/nvme0, /dev/nvme1).

namespaces.explicit: list of namespace paths (e.g., /dev/nvme1n1). If set, testing will run only on these namespaces for matching controllers.

Include/exclude regex still work; explicit lists take precedence.

✅ Keeps all previous features (format/sanitize, WP, mkfs/mount, fio_on_fs, power-state sampling, sensors, turbostat, telemetry log, JSON+HTML reports).

✅ Root-sensitive calls still run with sudo -n and you can use --sudo to auto-elevate.





Example config.yaml (explicit device selection)
output_dir: ./nvme_reports

smart: { duration: 45, interval: 5 }

fio:
  runtime: 45
  iodepth: 8
  bs: 4k
  ioengine: io_uring
  workloads: [randread, randwrite]

# Choose controllers explicitly (optional)
controllers:
  explicit: ["/dev/nvme0", "/dev/nvme1"]   # <- test only these controllers
  include_regex: ".*"
  exclude_regex: ""

# Or choose namespaces explicitly (optional)
namespaces:
  explicit: ["/dev/nvme1n1"]               # <- test only this namespace (per matching controller)
  include_regex: ".*"
  exclude_regex: ""

# Destructive ops (off by default)
sanitize: { enabled: false, action: "none" }
format:   { enabled: false, lbaf: 0, ses: 0 }

write_protect: { enabled: false, value: 1 }

filesystem:
  create: true
  type: ext4
  mkfs_options: "-F"
  mount: true
  mount_base: "/mnt/nvmeqa"
  mount_options: "defaults,noatime"
  fio_on_fs: true
  fio_file_size: "8G"
  fio_file_prefix: "fio_nvmeqa"

telemetry:
  sensors_interval: 2
  turbostat_interval: 2
  nvme_telemetry: true
  power_interval: 2



If you set both controllers.explicit and namespaces.explicit, the script:

loops over controllers.explicit and

for each controller, uses only the namespaces.explicit entries that belong to that controller.

Run (with auto-elevation if needed)
python3 nvme_qa.py --config config.yaml --sudo


This version won’t generate /dev/nvme1n1n1, and you can precisely control which devices are tested. If you still see anything odd in the HTML, share the exact paths it printed and I’ll tune the parser further.
