"""
extra_script.py
================
Fuegt PlatformIO "Custom Targets" hinzu, die im PlatformIO-Sidebar
(Project Tasks -> teensy40 -> Custom) als eigene, klickbare Eintraege
erscheinen:

  - Upload BT: Node 1
  - Upload BT: Node 2
  - Upload BT: Both

Jeder dieser Targets baut zuerst ganz normal (dependencies=["buildprog"])
und ruft danach das bestehende pc_flash_tool/bt_flash_sender.py mit dem
frisch gebauten .hex auf. Kein Aenderungsbedarf an bt_flash_sender.py.

Aktivierung in platformio.ini:
    extra_scripts = post:extra_script.py
"""
import os
import sys

Import("env")

PROJECT_DIR = env["PROJECT_DIR"]
SENDER_SCRIPT = os.path.normpath(
    os.path.join(PROJECT_DIR, "..", "pc_setup", "pc_flash_tool", "bt_flash_sender.py")
)

# Python-Interpreter des aktuellen PlatformIO-venv verwenden (robust unter Win/Linux/Mac)
PYTHON_EXE = sys.executable

TARGETS = [
    ("upload_bt_node1", "node1", "Upload BT: Node 1"),
    ("upload_bt_node2", "node2", "Upload BT: Node 2"),
    ("upload_bt_both",  "both",  "Upload BT: Both"),
]

for target_name, bt_target, title in TARGETS:
    env.AddCustomTarget(
        name=target_name,
        dependencies=["buildprog"],   # <- erzwingt vorherigen Build
        actions=[
            " ".join([
                f'"{PYTHON_EXE}"',
                f'"{SENDER_SCRIPT}"',
                '"$BUILD_DIR/firmware.hex"',
                "--target", bt_target,
            ])
        ],
        title=title,
        description=f"Build + Bluetooth-Flash auf {bt_target}",
        always_build=True,
    )
