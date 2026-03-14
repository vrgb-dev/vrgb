![VRGB Logo](assets/vrgb-logo.png)

# VRGB

Userspace RGB control for ASUS HID LampArray keyboards on Linux.

No kernel mods.  
No daemon.  
Just HID.

---

## Overview

VRGB is a lightweight Linux CLI utility for controlling RGB keyboards on certain ASUS laptops that expose the **HID LampArray interface**.

The project was developed and validated on:

**ASUS Vivobook S14 (S5406SA-WH79)**  
Keyboard controller: **ITE5570**

Unlike most RGB tools, VRGB does not rely on:

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

Clone the repository and run the installer.


git clone https://github.com/vrgb-dev/vrgb.git

cd vrgb
chmod +x install.sh
./install.sh


The installer will:

- install `vrgb` to `/usr/local/bin`
- create the `vrgb` group if necessary
- add your user to the group
- install a udev rule
- reload udev rules

After installation, **log out and log back in** so the group permissions apply.

---

## Command Reference

### Show Status


vrgb status


Displays detected device and saved configuration.

---

### Set RGB Color


vrgb set RRGGBB [percent]


Example:


vrgb set 00aa55 65


---

### Change Brightness


vrgb brightness 80


Range: **0–100**

---

### Turn Lighting Off


vrgb off


---

### Restore Saved State


vrgb restore


Useful for login autostart.

---

### Firmware Autonomous Mode

Enable firmware controlled lighting:


vrgb auto on


Return control to VRGB:


vrgb auto off


---

### OEM Rainbow Mode

Toggle ASUS firmware rainbow mode:


vrgb rainbow on
vrgb rainbow off


Note: On some systems this may require `sudo`.

---

### Debug Mode


vrgb --debug status


Shows HID device detection and report details.

---

### About


vrgb about


Displays project information and ASCII banner.

---

## Manual Installation

If you prefer not to use the installer script.

### Install Binary


sudo install -m 755 vrgb.py /usr/local/bin/vrgb


### Create Access Group


sudo groupadd -f vrgb
sudo usermod -aG vrgb $USER


### Install udev Rule

Create the file:


/etc/udev/rules.d/99-vrgb.rules


Contents:


SUBSYSTEM=="hidraw", KERNELS=="i2c-ITE5570*", MODE="0660", GROUP="vrgb"


### Reload udev


sudo udevadm control --reload-rules
sudo udevadm trigger


Log out and log back in afterward.

---

## Optional KDE Autostart Restore

Some ASUS firmware resets keyboard color at boot.

Create:


~/.config/autostart/vrgb.desktop


Contents:


[Desktop Entry]
Type=Application
Exec=/usr/local/bin/vrgb restore
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=VRGB Restore
Comment=Restore keyboard RGB state


---

## Uninstall

Run:


./uninstall.sh


This removes:

- `/usr/local/bin/vrgb`
- the udev rule
- optional autostart entry

The `vrgb` group is intentionally left intact.

---

## Project Philosophy

VRGB intentionally avoids complexity.

Design goals:

- no background daemon
- no kernel modules
- no runtime dependencies
- reversible installation
- minimal attack surface
- transparent hardware access

The project focuses on **reliable static RGB control**, not heavy animation engines.

---

## Changelog

### v0.2.2

Initial public release polish.

Changes:

- Added ASCII banner and `about` command
- Improved CLI help output
- Clarified saved mode reporting
- Updated installer udev rule
- Validated full install → uninstall → reinstall workflow
- Confirmed non-root HID access
- Added release archive structure

---

### v0.2.0

Major stability improvements.

Additions:

- automatic hidraw device discovery
- debug mode
- persistent configuration storage
- installer script
- udev permission model

---

### v0.1.0

Initial prototype.

Features:

- basic HID device detection
- static RGB color control
- brightness scaling
- restore functionality

---

## Roadmap

Possible future improvements:

- saved profiles
- expanded ASUS device compatibility
- improved firmware state detection
- GUI frontend
- breathing / fade effects

---

## License

MIT License

---

## Repository

https://github.com/vrgb-dev/vrgb
