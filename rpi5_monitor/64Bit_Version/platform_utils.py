import os
import sys
import subprocess
import platform
import logging

log = logging.getLogger(__name__)

def setup_hotspot(ssid: str = "RoboDebug", key: str = "robodebug123"):
    """Create a local Wi‑Fi hotspot on Windows using netsh.
    On non‑Windows platforms the function is a no‑op.
    """
    if platform.system() != "Windows":
        log.info("Hotspot setup skipped (non‑Windows platform)")
        return

    # Ensure we have admin rights – netsh will fail otherwise.
    try:
        # Check admin by attempting a benign netsh command.
        subprocess.check_output(["netsh", "wlan", "show", "drivers"], stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        log.error("Admin rights required for hotspot setup: %s", e.output.decode())
        return
    
    # Configure and start the hosted network.
    try:
        subprocess.check_call(["netsh", "wlan", "set", "hostednetwork", "mode=allow", f"ssid={ssid}", f"key={key}"])
        subprocess.check_call(["netsh", "wlan", "start", "hostednetwork"])
        log.info("Hosted network '%s' started.", ssid)
    except subprocess.CalledProcessError as e:
        log.error("Failed to configure/start hotspot: %s", e)
        return

    # Open firewall ports for UDP/TCP communication.
    ports = ["5001", "5002"]
    for port in ports:
        for proto in ["UDP", "TCP"]:
            try:
                subprocess.check_call([
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    f"name=RoboDebug {proto} Port {port}", "dir=in", "action=allow",
                    f"protocol={proto.lower()}", f"localport={port}"
                ])
            except subprocess.CalledProcessError:
                log.warning("Could not add firewall rule for %s %s", proto, port)
    log.info("Firewall rules added.")
