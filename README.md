<p align="center">
  <img src="assets/vrgblogodark.png" width="500"><br>
  <br>
  RGB control for ASUS Vivobook HID LampArray keyboards on Linux<br>
</p>



## Overview

VRGB is a lightweight Linux CLI utility for controlling RGB keyboards on
Vivobook ASUS laptops that expose the HID LampArray interface.


**Why this exists:**

I bought a Vivobook S14 and put Fedora on it for school and work. Fn brightness worked, but the keyboard was stuck on white and none of the usual ASUS RGB tools did anything. After digging into it, I found the keyboard wasn't using the typical ASUS control path at all.

VRGB is just a tool built around that discovery to get simple RGB control working on Linux without touching the kernel or running a daemon.

<br>

**The project was developed and validated on:**

ITE5570 (HID_ID: 0018:00000B05:000019B6)  
- ASUS Vivobook S14 (S5406SA-WH79)  
- firmware: 0x0B  
- color: 0x05  

**Community validated:**

ITE5570 (HID_ID: 0018:00000B05:00005570)  
- ASUS Vivobook S16 series (M5606K / M5606WA)  
- firmware: 0x46  
- color: 0x45  
- note: OEM rainbow may not function on all models  

<br>

Unlike some RGB tools, VRGB does not rely on kernel patches, vendor utilities, controller hacks, or reverse-engineered Windows drivers. VRGB simply communicates with the keyboard controller through the Linux HID subsystem. 

<br>


**Control path:**

    vrgb.py
       ↓
    /dev/hidrawX
       ↓
    ITE5570 keyboard controller
       ↓
    RGB lighting

Current Stable Release: v0.4.0
    

## Example Usage

<p align="center">
  <img src="assets/vrgb-demo.png" width="400">
</p>


## Features

-   Static RGB color control
-   Fine brightness scaling (0–100%)
-   Custom profiles
-   Firmware autonomous mode toggle
-   OEM rainbow toggle (sudo required)
-   Smooth HSV color cycle (background daemon)
-   Ambient screen color sync (background daemon)
-   Debug diagnostics
-   Persistent configuration
-   Installer and uninstaller included
-   Non-root daily usage via udev permissions
-   Optional autostart restore



## Supported Hardware

VRGB supports ASUS laptops that expose the **ITE5570 HID LampArray controller**.

Support is based on **verified device mappings**, not specific laptop models.

### Verified mappings

**ITE5570 (HID_ID: 0018:00000B05:000019B6)**  
- confirmed on: ASUS Vivobook S14 (S5406SA)  
- firmware report: `0x0B`  
- color report: `0x05`
- **requires:** `asus-nb-wmi` kernel module (see note below)

**ITE5570 (HID_ID: 0018:00000B05:00005570)**  
- confirmed on: ASUS Vivobook S16 series (M5606K / M5606WA)  
- firmware report: `0x46`  
- color report: `0x45`  
- note: OEM rainbow mode may not function on all models

### Example device identifiers

    HID_NAME=ITE5570:00 0B05:19B6
    HID_ID=0018:00000B05:000019B6


## Compatibility

VRGB scans available `hidraw` devices and selects compatible ASUS keyboard controllers automatically.

Multiple ASUS laptops appear to share the same ITE5570 controller and HID LampArray protocol. If your system exposes a similar device, there is a strong chance VRGB will work.

Support expands through **verified device mappings** as new hardware is tested. Stability and correctness are prioritized over broad but unreliable compatibility.

If VRGB works (or does not work) on your system, please submit a compatibility report including:

    vrgb --debug status

Community reports help identify new supported devices quickly.

See reports here:  
https://github.com/vrgb-dev/vrgb/issues/1


## Quick Install

Clone the repository and run the installer.

    git clone https://github.com/vrgb-dev/vrgb.git
    cd vrgb
    chmod +x install.sh
    ./install.sh

After installation log out and log back in so group permissions apply.


**Note:**
Keyboard color persists on reboot, but may reset to firmware default after a full power cycle.
Use the autostart option in the installer (or set it manually) to reapply your configuration automatically.


### Note for ASUS Vivobook S14 (HID_ID: 0018:00000B05:000019B6)

The ITE5570 I2C-HID firmware on this device ignores all LampArray HID commands until
the `asus-nb-wmi` kernel module initializes the hardware via WMI.
Without it, commands complete without error but the keyboard color never changes.

Load the module once:

    sudo modprobe asus-nb-wmi

Load it automatically at boot:

    echo 'asus-nb-wmi' | sudo tee /etc/modules-load.d/asus-nb-wmi.conf

VRGB will print a clear error message if the module is missing.



## Command List

Show Current Status

    vrgb status

Set RGB Color

    vrgb set RRGGBB [brightness %]

*Example:*

    vrgb set 00aa55 65

Change Brightness

    vrgb brightness 80
    
Save Profile (Current State)

    vrgb profile save fedorablue
    
Load Profile

    vrgb profile load fedorablue
    
Delete Profile

    vrgb profile delete fedorablue
    
List Saved Profiles

    vrgb profile list

Turn Lighting Off

    vrgb off

Restore Saved State

    vrgb restore

Enable Firmware Lighting (Firmware Autonomous Mode)

    vrgb auto on

Return control to VRGB:

    vrgb auto off

OEM Rainbow Mode (requires sudo)

    sudo vrgb rainbow on
    sudo vrgb rainbow off

Smooth HSV Color Cycle

Starts a background process that smoothly cycles through the full color wheel.

    vrgb cycle on [speed] [brightness]
    vrgb cycle off

*Examples:*

    vrgb cycle on            # default speed, 100% brightness
    vrgb cycle on 2 80       # 2× faster, 80% brightness
    vrgb cycle on 0.3        # slow fade

Ambient Screen Color Sync

Starts a background process that reads the dominant vivid color from the screen
and sets the keyboard to match — updating smoothly at the given interval.
Requires Pillow: `pip install Pillow`

    vrgb ambient on [--interval S] [--brightness N] [--transition S]
    vrgb ambient off

*Options:*

| Flag | Default | Description |
|---|---|---|
| `--interval` | `0.5` | Seconds between screen captures |
| `--brightness` | `100` | Keyboard brightness 0–100 |
| `--transition` | `1.0` | Seconds to lerp from old color to new color |

*Examples:*

    vrgb ambient on                                   # defaults
    vrgb ambient on --interval 1 --transition 2       # slower, smoother
    vrgb ambient on --interval 0.3 --brightness 70    # fast capture, dimmer

`cycle` and `ambient` are mutually exclusive — starting one stops the other automatically.

Debug Mode

    vrgb --debug status

About

    vrgb about


## Manual Installation

Install Binary

    sudo install -m 755 vrgb.py /usr/local/bin/vrgb

Create Access Group

    sudo groupadd -f vrgb
    sudo usermod -aG vrgb $USER

Install udev Rule

Create:

    /etc/udev/rules.d/99-vrgb.rules

Contents:

    SUBSYSTEM=="hidraw", KERNELS=="i2c-ITE5570*", MODE="0660", GROUP="vrgb"

Reload udev

    sudo udevadm control --reload-rules
    sudo udevadm trigger

Log out and log back in afterward.



## Optional Autostart Restore

Create:

    ~/.config/autostart/vrgb-restore.desktop

Contents:

    [Desktop Entry]
    Type=Application
    Exec=/usr/local/bin/vrgb restore
    Hidden=false
    NoDisplay=false
    X-GNOME-Autostart-enabled=true
    Name=VRGB Restore
    Comment=Restore keyboard RGB state



## Uninstall

    ./uninstall.sh

Removes:

-   /usr/local/bin/vrgb
-   the udev rule
-   optional autostart entry



## Changelog

v0.4.0

- fix(ITE5570/I2C): `asus-nb-wmi` kernel module is now required for HID_ID `0018:00000B05:000019B6`; vrgb prints a clear error with load instructions if it is missing
- fix: OEM rainbow (`vrgb rainbow on`) now prints an error instead of silently doing nothing on devices where WMI dev_id `0x0005002f` is unsupported
- feat: `vrgb cycle on/off` — smooth HSV color wheel running as a background daemon
- feat: `vrgb ambient on/off` — screen dominant vivid color sync running as a background daemon; supports `--interval`, `--brightness`, `--transition` flags
- `cycle` and `ambient` are mutually exclusive; starting one stops the other
- added `extras/vrgb-cycle` standalone script
- version bump: 0.3.1 → 0.4.0

v0.3.1

- introduced multi-device support architecture
- replaced hardcoded HID targeting with device mappings
- added support for ITE5570 (0x5570) devices
- confirmed working on additional Vivobook S16 hardware (community tested)
- refactored device detection to return structured device info
- eliminated global report ID assumptions
- no behavioral changes for existing supported devices

v0.3

-    added named profile support
-    profile save/load/list/delete commands
-    profile data stored in config.json
-    profile load applies immediately to hardware
-    non-HID commands no longer require device detection

v0.2.2

-   improved CLI help output
-   installer/Uninstaller validation
-   confirmed non-root HID access
-   release packaging

v0.2.0

-   automatic hidraw detection
-   debug mode
-   persistent config
-   installer script

v0.1

Initial prototype with static RGB and brightness control.



## License

MIT License

## Repository

https://github.com/vrgb-dev/vrgb
