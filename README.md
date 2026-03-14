# ![VRGB Logo](assets/vrgb-logo.png)

# VRGB

**Userspace RGB control for ASUS Vivobook HID LampArray keyboards on Linux**

No kernel mods. No daemon. Just HID.

---

## What is VRGB?

VRGB is a lightweight Linux CLI utility for controlling RGB keyboards on certain ASUS (built and tested on a Vivobook S14 - S5406SA-WH79) laptops that expose a standard HID LampArray interface.

Instead of relying on kernel patches, EC hacks, vendor utilities, or background daemons, VRGB talks directly to the keyboard controller through `/dev/hidraw`.

Current stable release: **v0.2.2**

---

## Features

- Static RGB color control
- Fine brightness control from 0 to 100%
- Firmware autonomous mode toggle
- OEM rainbow toggle
- Debug mode
- Persistent saved config
- Optional KDE autostart restore
- Installer and uninstaller included
- Non-root daily use through udev permissions

---

## Supported hardware

Currently validated on:

- **ASUS Vivobook S14 (S5406SA)**
- Keyboard controller: **ITE5570**
- Interface: **HID LampArray (Usage Page 0x59)**

Example device identifiers:

```text
HID_NAME=ITE5570:00 0B05:19B6
HID_ID=0018:00000B05:000019B6

---

## Quick Install

```bash
git clone https://github.com/vrgb-dev/vrgb.git
cd vrgb
chmod +x install.sh
./install.sh

Log out and log back in after installation.

---

## Commands

Show device status:

vrgb status

Set RGB color:

vrgb set 00aa55 65

Change brightness:

vrgb brightness 80

Turn lights off:

vrgb off

Restore saved state:

vrgb restore
