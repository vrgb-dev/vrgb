<p align="center">
  <img src="assets/vrgblogodark.png" width="500"><br>
  <br>
  RGB control for ASUS Vivobook HID LampArray keyboards on Linux<br>
</p>



## Overview

VRGB is a lightweight Linux CLI utility for controlling RGB keyboards on
certain ASUS laptops that expose the HID LampArray interface.


**Why this exists:**

I bought a Vivobook S14 and put Fedora on it for school and work. Fn brightness worked, but the keyboard was stuck on white and none of the usual ASUS RGB tools did anything. After digging into it, I found the keyboard wasn’t using the typical ASUS control path at all. It exposed a HID LampArray device instead.

VRGB is just a small script built around that discovery to get simple RGB control working on Linux without touching the kernel or running a daemon.

<br>

**The project was developed and validated on:**

ASUS Vivobook S14 (S5406SA-WH79)

Keyboard controller: ITE5570

<br>

Unlike some RGB tools, VRGB does not rely on kernel patches, vendor utilities, background daemons, controller hacks, or reverse-engineered Windows drivers. VRGB simply communicates with the keyboard controller through the Linux HID subsystem. 

<br>


**Control path:**

    vrgb.py
       ↓
    /dev/hidrawX
       ↓
    ITE5570 keyboard controller
       ↓
    RGB lighting

Current stable release: v0.2.2

## Example Usage

<p align="center">
  <img src="assets/vrgb-demo.png" width="550">
</p>


## Features

-   Static RGB color control
-   Fine brightness scaling (0–100%)
-   Firmware autonomous mode toggle
-   OEM rainbow toggle (sudo required)
-   Debug diagnostics
-   Persistent configuration
-   Installer and uninstaller included
-   Non-root daily usage via udev permissions
-   Optional KDE autostart restore



## Supported Hardware

Currently validated on:

-   ASUS Vivobook S14 (S5406SA)
-   Keyboard controller: ITE5570
-   Interface: HID LampArray (Usage Page 0x59)

Example device identifiers:

    HID_NAME=ITE5570:00 0B05:19B6
    HID_ID=0018:00000B05:000019B6



## Compatibility

VRGB scans available hidraw devices and selects the matching ASUS keyboard controller automatically.

Other ASUS laptops using the same controller may work but require
testing. Community reports are more than welcome. If vrgb works (or doesn't) work on your system, please click the Hardware Compatibility Reports issue below and post your *vrgb --debug status* output. This will help the project immensely.

See community reports here:  
https://github.com/vrgb-dev/vrgb/issues/1



## Quick Install

Clone the repository and run the installer.

    git clone https://github.com/vrgb-dev/vrgb.git
    cd vrgb
    chmod +x install.sh
    ./install.sh

After installation log out and log back in so group permissions apply.



## Command List

Show Current Status

    vrgb status

Set RGB Color

    vrgb set RRGGBB [brightness %]

*Example:*

    vrgb set 00aa55 65

Change Brightness

    vrgb brightness 80

Turn Lighting Off

    vrgb off

Restore Saved State

    vrgb restore

Enable firmware lighting (Firmware Autonomous Mode)

    vrgb auto on

Return control to VRGB:

    vrgb auto off

OEM Rainbow Mode (requires sudo)

    sudo vrgb rainbow on
    sudo vrgb rainbow off

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



## Optional KDE Autostart Restore

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



## Uninstall

    ./uninstall.sh

Removes:

-   /usr/local/bin/vrgb
-   the udev rule
-   optional autostart entry



## Future Development

Planned roadmap:

- profile support
- expanded ASUS hardware compatibility
- GUI frontend
- breathing / fade effects

With future updates in mind, this project will aim to continue to be as efficient and lightweight as possible.



## Changelog

v0.2.2

-   Improved CLI help output
-   Installer/Uninstaller validation
-   Confirmed non-root HID access
-   Release packaging

v0.2.0

-   automatic hidraw detection
-   debug mode
-   persistent config
-   installer script

v0.1.0

Initial prototype with static RGB and brightness control.



## License

MIT License

## Repository

https://github.com/vrgb-dev/vrgb
