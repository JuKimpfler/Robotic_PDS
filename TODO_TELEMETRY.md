# Telemetry Implementation TODO

Last updated: 2026-06-05

## Core Tasks
- [ ] Create base configs and shared protocol docs
- [ ] Implement Go backend core (config, UDP, ring buffer, WS, HTTP, metrics, simulate)
- [ ] Implement Go backend extras (channel hot-reload, plugins, hotspot, rate control, params, robot viz)
- [ ] Implement RPi bridge C daemon (SPI, GPIO IRQ, UDP split, CRC, simulate)
- [ ] Implement frontend UI (header, tabs, DataTable, Plotter)
- [ ] Add frontend skeleton tabs (RobotViz, Parameters)
- [ ] Add setup/install scripts
- [ ] Validate builds/tests

## Notes
- Follow README_TELEMETRY_SYSTEM.md spec exactly.
- Keep config-driven paths; avoid hardcoded values.
