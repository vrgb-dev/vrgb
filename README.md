[VRGB Logo]

VRGB

Userspace RGB control for ASUS HID LampArray keyboards on Linux.

No kernel mods.
No daemon.
Just HID.

------------------------------------------------------------------------

Overview

VRGB is a lightweight Linux CLI utility for controlling RGB keyboards on
certain ASUS laptops that expose the HID LampArray interface.

The project was developed and validated on:

ASUS Vivobook S14 (S5406SA-WH79)
Keyboard controller: ITE5570

Unlike most RGB tools, VRGB does not rely on:

-   kernel patches
-   vendor utilities
-   background daemons
-   embedded controller hacks
-   reverse engineered Windows drivers

Instead, VRGB communicates directly with the keyboard controller through
the Linux HID subsystem.

Control path:

    vrgb.py
       ↓
    /dev/hidrawX
       ↓
    ITE5570 keyboard controller
       ↓
    RGB lighting

This keeps the project:

-   simple
-   transparent
-   portable
-   secure

Current stable release: v0.2.2

------------------------------------------------------------------------

Features

-   Static RGB color control
-   Fine brightness scaling (0–100%)
-   Firmware autonomous mode toggle
-   Optional OEM rainbow toggle
-   Debug diagnostics
-   Persistent configuration
-   Installer and uninstaller included
-   Non-root daily usage via udev permissions
-   Optional KDE autostart restore

------------------------------------------------------------------------

Supported Hardware

Currently validated on:

-   ASUS Vivobook S14 (S5406SA)
-   Keyboard controller: ITE5570
-   Interface: HID LampArray (Usage Page 0x59)

Example device identifiers:

    HID_NAME=ITE5570:00 0B05:19B6
    HID_ID=0018:00000B05:000019B6

Other ASUS laptops using the same controller may work but require
testing.

Community reports are welcome.

------------------------------------------------------------------------

Quick Install

Clone the repository and run the installer.

    git clone https://github.com/vrgb-dev/vrgb.git
    cd vrgb
    chmod +x install.sh
    ./install.sh

After installation log out and log back in so group permissions apply.

------------------------------------------------------------------------

Command Reference

Show Status

    vrgb status

Set RGB Color

    vrgb set RRGGBB [percent]

Example:

    vrgb set 00aa55 65

Change Brightness

    vrgb brightness 80

Range: 0–100

Turn Lighting Off

    vrgb off

Restore Saved State

    vrgb restore

Firmware Autonomous Mode

Enable firmware lighting:

    vrgb auto on

Return control to VRGB:

    vrgb auto off

OEM Rainbow Mode

    vrgb rainbow on
    vrgb rainbow off

Debug Mode

    vrgb --debug status

About

    vrgb about

------------------------------------------------------------------------

Manual Installation

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

------------------------------------------------------------------------

Optional KDE Autostart Restore

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

------------------------------------------------------------------------

Uninstall

    ./uninstall.sh

Removes:

-   /usr/local/bin/vrgb
-   the udev rule
-   optional autostart entry

------------------------------------------------------------------------

Project Philosophy

VRGB intentionally avoids complexity.

Design goals:

-   no background daemon
-   no kernel modules
-   no runtime dependencies
-   reversible installation
-   minimal attack surface
-   transparent hardware access

------------------------------------------------------------------------

Changelog

v0.2.2

-   Added ASCII banner and about command
-   Improved CLI help output
-   Installer polish
-   Confirmed non-root HID access

v0.2.0

-   automatic hidraw detection
-   debug mode
-   persistent config
-   installer script

v0.1.0

Initial prototype with static RGB and brightness control.

------------------------------------------------------------------------

License

MIT License

------------------------------------------------------------------------

Repository

https://github.com/vrgb-dev/vrgb
