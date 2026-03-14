![VRGB Logo](assets/vrgb-logo.png)

# VRGB

**Userspace RGB control for ASUS HID LampArray keyboards on Linux**

No kernel mods.  
No daemon.  
Just HID.

---

## Overview

VRGB is a lightweight Linux CLI utility for controlling RGB keyboards on certain ASUS laptops that expose the **HID LampArray interface**.

The project was developed and validated on:

**ASUS Vivobook S14 (S5406SA-WH79)**  
Keyboard controller: **ITE5570**

Unlike most RGB tools, VRGB **does not rely on**:

- kernel patches
- vendor utilities
- background daemons
- embedded controller hacks
- reverse engineered Windows drivers

Instead, VRGB communicates directly with the keyboard controller through the Linux HID subsystem.

Control path:

vrgb.py
↓
/dev/hidrawX
↓
ITE5570 keyboard controller
↓
RGB lighting


This keeps the project:

- simple
- transparent
- portable
- secure

Current stable release: **v0.2.2**

---

## Features

- Static RGB color control
- Fine brightness scaling (0–100%)
- Firmware autonomous mode toggle
- Optional OEM rainbow toggle
- Debug diagnostics
- Persistent configuration
- Installer and uninstaller included
- Non-root daily usage via udev permissions
- Optional KDE autostart restore

---

## Supported Hardware

Currently validated on:

- **ASUS Vivobook S14 (S5406SA)**
- Keyboard controller: **ITE5570**
- Interface: **HID LampArray (Usage Page 0x59)**

Example device identifiers:
HID_NAME=ITE5570:00 0B05:19B6
HID_ID=0018:00000B05:000019B6


Other ASUS laptops using the same controller may work but require testing.

Community reports are welcome.

---

## Quick Install

Clone the repository and run the installer:

```bash
git clone https://github.com/vrgb-dev/vrgb.git
cd vrgb
chmod +x install.sh
./install.sh

The installer will:

- install vrgb to /usr/local/bin

- create the vrgb group if necessary

- add your user to the group

- install a udev rule

- reload udev rules

After installation:

log out and log back in so the new group permissions apply.
