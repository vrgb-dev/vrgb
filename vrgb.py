#!/usr/bin/env python3

import os
import sys
import json
import fcntl
import pwd
from pathlib import Path

# ===== Debug =====

DEBUG = False


def debug(msg):
    if DEBUG:
        print(f"[debug] {msg}")


# ===== Constants =====

HIDIOCSFEATURE_BASE = 0xC0004806


def HIDIOCSFEATURE(length: int) -> int:
    return HIDIOCSFEATURE_BASE | (length << 16)


def get_real_home() -> Path:
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except KeyError:
            pass
    return Path.home()


CONFIG_DIR = get_real_home() / ".config" / "vrgb"
CONFIG_FILE = CONFIG_DIR / "config.json"

TARGET_HID_ID = "0018:00000B05:000019B6"
TARGET_HID_NAME = "ITE5570:00 0B05:19B6"

HOST_BYTE = 0x00
FIRMWARE_BYTE = 0x01

ASUS_WMI_BASE = Path("/sys/kernel/debug/asus-nb-wmi")
ASUS_WMI_METHOD_ID = ASUS_WMI_BASE / "method_id"
ASUS_WMI_DEV_ID = ASUS_WMI_BASE / "dev_id"
ASUS_WMI_CTRL_PARAM = ASUS_WMI_BASE / "ctrl_param"
ASUS_WMI_DEVS = ASUS_WMI_BASE / "devs"

VERSION = "0.2.2"
PROJECT_URL = "https://github.com/<your-username>/vrgb"

# ===== Utilities =====

def die(msg, exit_code=1):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(exit_code)


def clamp(n, lo, hi):
    return max(lo, min(hi, n))


def percent_to_intensity(p):
    p = clamp(int(p), 0, 100)
    return round(p * 255 / 100)


def hex_to_rgb(hexstr):
    hexstr = hexstr.strip().lower().replace("#", "")
    if len(hexstr) != 6:
        die("Color must be RRGGBB")

    try:
        r = int(hexstr[0:2], 16)
        g = int(hexstr[2:4], 16)
        b = int(hexstr[4:6], 16)
    except ValueError:
        die("Invalid hex color")

    return r, g, b


# ===== Config =====

def default_config():
    return {
        "color": "aa00ff",
        "percent": 100,
        "last_on_percent": 100,
        "autonomous": False,
    }


def load_config():
    if not CONFIG_FILE.exists():
        return default_config()

    try:
        cfg = json.loads(CONFIG_FILE.read_text())
    except json.JSONDecodeError:
        backup = CONFIG_FILE.with_suffix(CONFIG_FILE.suffix + ".bad")
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.replace(backup)
            print(
                f"Warning: config file corrupted. Backed up to {backup} and using defaults.",
                file=sys.stderr,
            )
        except OSError:
            print(
                "Warning: config file corrupted. Could not back it up; using defaults.",
                file=sys.stderr,
            )
        return default_config()

    defaults = default_config()

    cfg.setdefault("color", defaults["color"])
    cfg.setdefault("percent", defaults["percent"])
    cfg.setdefault("last_on_percent", defaults["last_on_percent"])
    cfg.setdefault("autonomous", defaults["autonomous"])

    try:
        r, g, b = hex_to_rgb(cfg["color"])
        cfg["color"] = f"{r:02x}{g:02x}{b:02x}"
    except SystemExit:
        cfg["color"] = defaults["color"]

    try:
        cfg["percent"] = clamp(int(cfg["percent"]), 0, 100)
    except (TypeError, ValueError):
        cfg["percent"] = defaults["percent"]

    try:
        cfg["last_on_percent"] = clamp(int(cfg["last_on_percent"]), 0, 100)
    except (TypeError, ValueError):
        cfg["last_on_percent"] = defaults["last_on_percent"]

    cfg["autonomous"] = bool(cfg["autonomous"])

    return cfg


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


# Config semantics:
#   color            -> saved static RGB hex used for host/manual restore
#   percent          -> current intended brightness, may be 0 after `off`
#   last_on_percent  -> last known non-zero brightness for restore behavior
#   autonomous       -> whether firmware/autonomous mode should be preserved

def get_saved_static_state(cfg):
    r, g, b = hex_to_rgb(cfg["color"])

    p = int(cfg.get("percent", 100))
    if p <= 0:
        p = int(cfg.get("last_on_percent", 100))
        if p <= 0:
            p = 100

    p = clamp(p, 0, 100)
    intensity = percent_to_intensity(p)

    return r, g, b, p, intensity


# ===== HID =====

def find_device():
    base = Path("/sys/class/hidraw")

    debug(f"Config file: {CONFIG_FILE}")

    if not base.exists():
        die("No hidraw devices found")

    best_match = None
    best_score = -1
    best_reason = "no match"

    for dev in sorted(base.iterdir()):
        uevent = dev / "device" / "uevent"

        if not uevent.exists():
            debug(f"{dev.name}: missing uevent")
            continue

        txt = uevent.read_text(errors="ignore")

        hid_id = None
        hid_name = None

        for line in txt.splitlines():
            if line.startswith("HID_ID="):
                hid_id = line.split("=", 1)[1].strip()
            elif line.startswith("HID_NAME="):
                hid_name = line.split("=", 1)[1].strip()

        score = -1
        reason = "no match"

        if hid_id == TARGET_HID_ID:
            score = 100
            reason = "exact HID_ID match"
        elif hid_name == TARGET_HID_NAME:
            score = 90
            reason = "exact HID_NAME match"

        debug(f"{dev.name}: hid_id={hid_id} hid_name={hid_name} score={score} reason={reason}")

        if score > best_score:
            best_score = score
            best_match = f"/dev/{dev.name}"
            best_reason = reason

    if best_match:
        debug(f"Selected device: {best_match} ({best_reason})")
        return best_match

    die("VRGB HID device not found")


def hid_set_feature(dev, report_id, payload_bytes):
    buf = bytes([report_id]) + payload_bytes
    debug(f"hid_set_feature dev={dev} report=0x{report_id:02X} payload={payload_bytes.hex()}")
    fd = os.open(dev, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.ioctl(fd, HIDIOCSFEATURE(len(buf)), buf)
    finally:
        os.close(fd)


def set_firmware_mode(dev, enabled: bool):
    debug(f"set_firmware_mode enabled={enabled}")
    hid_set_feature(dev, 0x0B, bytes([FIRMWARE_BYTE if enabled else HOST_BYTE]))


def set_color(dev, r, g, b, intensity):
    debug(f"set_color r={r} g={g} b={b} intensity={intensity}")

    payload = bytes([
        0x01,
        0x00, 0x00,
        0x00, 0x00,
        clamp(r, 0, 255),
        clamp(g, 0, 255),
        clamp(b, 0, 255),
        clamp(intensity, 0, 255),
    ])

    hid_set_feature(dev, 0x05, payload)


# ===== OEM Rainbow =====

def asus_wmi_write(method_id: str, dev_id: str, ctrl_param: str):
    ASUS_WMI_METHOD_ID.write_text(method_id)
    ASUS_WMI_DEV_ID.write_text(dev_id)
    ASUS_WMI_CTRL_PARAM.write_text(ctrl_param)
    _ = ASUS_WMI_DEVS.read_text(errors="ignore")


def asus_wmi_rainbow(enable: bool):
    debug(f"asus_wmi_rainbow enable={enable}")

    if not ASUS_WMI_BASE.exists():
        die("OEM rainbow not supported on this system.")

    for p in (ASUS_WMI_METHOD_ID, ASUS_WMI_DEV_ID, ASUS_WMI_CTRL_PARAM, ASUS_WMI_DEVS):
        if not p.exists():
            die("OEM rainbow interface incomplete.")

    asus_wmi_write(
        "0x00000001",
        "0x0005002f",
        "0x00000000" if enable else "0x00000001",
    )


# ===== Commands =====

def cmd_about():
    print(r"""
                 _
__   ___ __ __ _| |__
\ \ / / '__/ _` | '_ \
 \ V /| | | (_| | |_) |
  \_/ |_|  \__, |_.__/
           |___/

RGB control for ASUS HID LampArray keyboards

Version: """ + VERSION + """
""" + PROJECT_URL + """

No kernel mods. No daemon. Just HID.
""")

def cmd_status(cfg, dev):
    print("Device:", dev)
    print("Saved color:", "#" + cfg["color"])
    print("Saved brightness:", cfg["percent"], "%")
    print("Last-on brightness:", cfg["last_on_percent"], "%")
    mode = "firmware/autonomous" if cfg["autonomous"] else "host/static"
    print("Saved mode:", mode)
    debug(f"status complete mode={mode}")


def cmd_set(cfg, dev, color, percent=None):
    r, g, b = hex_to_rgb(color)

    if percent is None:
        percent = cfg["percent"]

    percent = clamp(int(percent), 0, 100)
    intensity = percent_to_intensity(percent)
    debug(f"cmd_set color={color} percent={percent} intensity={intensity}")

    set_firmware_mode(dev, False)
    set_color(dev, r, g, b, intensity)

    cfg["color"] = color.replace("#", "").lower()
    cfg["percent"] = percent
    if percent > 0:
        cfg["last_on_percent"] = percent
    cfg["autonomous"] = False
    save_config(cfg)


def cmd_brightness(cfg, dev, percent):
    r, g, b = hex_to_rgb(cfg["color"])

    percent = clamp(int(percent), 0, 100)
    intensity = percent_to_intensity(percent)
    debug(f"cmd_brightness percent={percent} intensity={intensity}")

    set_firmware_mode(dev, False)
    set_color(dev, r, g, b, intensity)

    cfg["percent"] = percent
    if percent > 0:
        cfg["last_on_percent"] = percent
    cfg["autonomous"] = False
    save_config(cfg)


def cmd_auto(cfg, dev, state):
    firmware_on = (state == "on")
    debug(f"cmd_auto state={state}")

    if firmware_on:
        set_firmware_mode(dev, True)
        cfg["autonomous"] = True
        save_config(cfg)
    else:
        r, g, b, p, intensity = get_saved_static_state(cfg)
        debug(f"cmd_auto off -> restore percent={p} intensity={intensity}")
        set_firmware_mode(dev, False)
        set_color(dev, r, g, b, intensity)
        cfg["percent"] = p
        cfg["autonomous"] = False
        save_config(cfg)


def cmd_rainbow(cfg, dev, state):
    enable = (state == "on")
    debug(f"cmd_rainbow state={state}")

    if enable:
        set_firmware_mode(dev, True)
        asus_wmi_rainbow(True)
        cfg["autonomous"] = True
        save_config(cfg)
    else:
        asus_wmi_rainbow(False)
        r, g, b, p, intensity = get_saved_static_state(cfg)
        debug(f"cmd_rainbow off -> restore percent={p} intensity={intensity}")
        set_firmware_mode(dev, False)
        set_color(dev, r, g, b, intensity)
        cfg["percent"] = p
        cfg["autonomous"] = False
        save_config(cfg)


def cmd_off(cfg, dev):
    r, g, b = hex_to_rgb(cfg["color"])
    debug("cmd_off")

    p = int(cfg.get("percent", 100))
    if p > 0:
        cfg["last_on_percent"] = p

    set_firmware_mode(dev, False)
    set_color(dev, r, g, b, 0)

    cfg["percent"] = 0
    cfg["autonomous"] = False
    save_config(cfg)


def cmd_restore(cfg, dev):

    if cfg.get("autonomous", False):
        debug("cmd_restore autonomous=True -> keep firmware mode")
        set_firmware_mode(dev, True)
        return

    r, g, b, p, intensity = get_saved_static_state(cfg)
    debug(f"cmd_restore percent={p} intensity={intensity}")

    set_firmware_mode(dev, False)
    set_color(dev, r, g, b, intensity)

    cfg["percent"] = p
    cfg["autonomous"] = False
    save_config(cfg)


# ===== Main =====

def main():
    global DEBUG

    args = sys.argv[1:]

    if args and args[0] == "--debug":
        DEBUG = True
        args = args[1:]

    if len(args) < 1:
        print("""Usage:
  vrgb status
  vrgb set RRGGBB [percent]
  vrgb brightness 0-100
  vrgb auto on|off
  vrgb rainbow on|off
  vrgb off
  vrgb restore
  vrgb about

----------------------------------------
Tip: use --debug before the command for diagnostic output
Example: vrgb --debug status
""")
        sys.exit(1)

    cfg = load_config()
    cmd = args[0]
    known_commands = {"status", "set", "brightness", "auto", "rainbow", "off", "restore", "about"}

    if cmd not in known_commands:
        die("Unknown command")

    dev = find_device()

    if cmd == "status":
        cmd_status(cfg, dev)

    elif cmd == "set":
        if len(args) < 2:
            die("Missing color")
        percent = args[2] if len(args) > 2 else None
        cmd_set(cfg, dev, args[1], percent)

    elif cmd == "brightness":
        if len(args) < 2:
            die("Missing percent")
        cmd_brightness(cfg, dev, args[1])

    elif cmd == "auto":
        if len(args) < 2 or args[1] not in ["on", "off"]:
            die("auto requires 'on' or 'off'")
        cmd_auto(cfg, dev, args[1])

    elif cmd == "rainbow":
        if len(args) < 2 or args[1] not in ["on", "off"]:
            die("rainbow requires 'on' or 'off'")
        cmd_rainbow(cfg, dev, args[1])

    elif cmd == "off":
        cmd_off(cfg, dev)

    elif cmd == "restore":
        cmd_restore(cfg, dev)

    elif cmd == "about":
        cmd_about()

    else:
        die("Unknown command")


if __name__ == "__main__":
    try:
        main()
    except PermissionError as e:
        path = getattr(e, "filename", None)
        if path and str(path).startswith(str(ASUS_WMI_BASE)):
            die("Permission denied to ASUS WMI debugfs. OEM rainbow requires sudo/root.")
        die("Permission denied to HID device. Run with sudo or install a udev rule.")
