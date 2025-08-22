# nvme-pcie-test

Changes to Test Plan

Device Detection (list_nvme_devices)

Use nvme-cli (nvme list -o json) instead of manual /dev/ enumeration.

This is more robust (handles namespaces, new devices) and avoids false positives.

Examples for Using Modular Functions

I’ll show multiple usage examples for each major function group (device, status, format, fs).

Add HTML Report Generator

Generate an HTML report with:

Device summary (PCIe + NVMe info)

Health (SMART logs, errors, warnings)

Thermal status

Using jinja2 for templating or just plain Python string templates.
