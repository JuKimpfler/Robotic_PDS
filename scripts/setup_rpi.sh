#!/usr/bin/env bash
# setup_rpi.sh — Hardening and optimization for Raspberry Pi Zero 2W.
# Deploys network settings, systemd service, and tunes CPU governor.
# Usage: sudo ./setup_rpi.sh

set -e

if [[ $EUID -ne 0 ]]; then
   echo "Dieses Skript muss als root ausgefuehrt werden (sudo ./setup_rpi.sh)"
   exit 1
fi

echo "1. Deaktiviere unnoetige Dienste..."
systemctl disable bluetooth avahi-daemon triggerhappy || true

echo "2. Richte CPU-Governor auf 'performance' ein..."
echo "performance" | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# Make governor persistent
apt-get install -y cpufrequtils || true
echo 'GOVERNOR="performance"' > /etc/default/cpufrequtils || true

echo "3. Optimiere Kernel-Netzwerkpuffer..."
if ! grep -q "net.core.rmem_max = 67108864" /etc/sysctl.conf; then
  echo "net.core.rmem_max = 67108864" >> /etc/sysctl.conf
  echo "net.core.wmem_max = 67108864" >> /etc/sysctl.conf
  sysctl -p
fi

echo "4. Konfiguriere /etc/systemd/system/spi-bridge.service..."
cat << 'EOF' > /etc/systemd/system/spi-bridge.service
[Unit]
Description=SPI-UDP Bridge
After=network.target

[Service]
ExecStart=/usr/local/bin/spi_bridge --spi /dev/spidev0.0 --host 192.168.137.1 --port 9000
CPUSchedulingPolicy=fifo
CPUSchedulingPriority=50
Restart=always
RestartSec=500ms
StandardOutput=journal

[Install]
WantedBy=multi-user.target
EOF

echo "5. Lade Systemd neu..."
systemctl daemon-reload
systemctl enable spi-bridge.service

echo "6. Bitte stellen Sie sicher, dass in /boot/config.txt folgende Zeilen eingetragen sind:"
echo "   dtparam=spi=on"
echo "   dtoverlay=spi0-1cs"
echo "   core_freq=250"
echo "   force_turbo=1"

echo "Setup beendet! Bitte neustarten."
