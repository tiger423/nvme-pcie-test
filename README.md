
How to run (to eliminate “permission denied” in your HTML)

Pick one:

# Option A: let the script elevate itself
python3 nvme_qa.py --config config.yaml --sudo

# Option B: run as root directly
sudo -E python3 nvme_qa.py --config config.yaml


That will allow privileged calls like nvme get-feature -f 2 -H, nvme telemetry-log, turbostat, sanitize, format, mkfs, and mount to succeed.

