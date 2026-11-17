#!/usr/bin/env python3

import os
import sys
import json
import fcntl
import pwd
import time
import colorsys
import subprocess
from pathlib import Path

# ===== Debug =====

DEBUG = False


def debug(msg):
    if DEBUG:
        print(f"[debug] {msg}")


# ===== Constants =====

HIDIOCSFEATURE_BASE = 0xC0004806


HIDIOCGFEATURE_BASE = 0xC0004807


def HIDIOCSFEATURE(length: int) -> int:
    return HIDIOCSFEATURE_BASE | (length << 16)


def HIDIOCGFEATURE(length: int) -> int:
    return HIDIOCGFEATURE_BASE | (length << 16)


def get_real_home() -> Path:
    # Resolve the invoking user's home even when elevated, so config lives under
    # the real user's ~/.config and not /root. sudo sets SUDO_USER; pkexec scrubs
    # the environment but sets PKEXEC_UID.
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except KeyError:
            pass

    pkexec_uid = os.environ.get("PKEXEC_UID")
    if pkexec_uid:
        try:
            return Path(pwd.getpwuid(int(pkexec_uid)).pw_dir)
        except (KeyError, ValueError):
            pass

    return Path.home()


CONFIG_DIR = get_real_home() / ".config" / "vrgb"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Verified devices. Report IDs are read from each device's HID report descriptor;
# the IDs here are the fallback when the descriptor cannot be read, and the
# remaining fields carry what a descriptor cannot tell (models, modules).
SUPPORTED_DEVICES = {
    "0018:00000B05:000019B6": {
        "hid_name": "ITE5570:00 0B05:19B6",
        "model": "ASUS Vivobook S14 series (ITE5570 0x19B6)",
        "confirmed_models": [
            "ASUS Vivobook S14 (S5406SA)",
        ],
        "firmware_report_id": 0x0B,
        "color_report_id": 0x05,
        "required_modules": ["asus-nb-wmi"],
    },
    "0018:00000B05:00005570": {
        "hid_name": "ITE5570:00 0B05:5570",
        "model": "ASUS Vivobook S series (ITE5570 0x5570)",
        "confirmed_models": [
            "ASUS Vivobook S16 (M5606K)",
            "ASUS Vivobook S16 (M5606WA)",
            "ASUS Vivobook S14 (M5406WA)",
            "ASUS Vivobook S16 (M5606UA)",
            "ASUS Vivobook S15 (M5506NA)",
        ],
        "firmware_report_id": 0x46,
        "color_report_id": 0x45,
    },
}

# HID LampArray usage page (0x59) and the report usages VRGB talks to.
LAMPARRAY_USAGE_PAGE = 0x59
LAMPARRAY_ATTRIBUTES_REPORT = 0x02
LAMPARRAY_RANGE_UPDATE_REPORT = 0x60
LAMPARRAY_CONTROL_REPORT = 0x70

HOST_BYTE = 0x00
FIRMWARE_BYTE = 0x01

VERSION = "1.1.0"
PROJECT_URL = "https://github.com/vrgb-dev/vrgb"

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
        "profiles": {},
    }


def normalize_profile(profile, defaults):
    if not isinstance(profile, dict):
        return None

    normalized = {}

    try:
        r, g, b = hex_to_rgb(profile.get("color", defaults["color"]))
        normalized["color"] = f"{r:02x}{g:02x}{b:02x}"
    except SystemExit:
        normalized["color"] = defaults["color"]

    try:
        normalized["percent"] = clamp(
            int(profile.get("percent", defaults["percent"])), 0, 100
        )
    except (TypeError, ValueError):
        normalized["percent"] = defaults["percent"]

    normalized["autonomous"] = bool(
        profile.get("autonomous", defaults["autonomous"])
    )

    return normalized


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
    cfg.setdefault("profiles", defaults["profiles"])

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

    if not isinstance(cfg["profiles"], dict):
        cfg["profiles"] = {}
    else:
        normalized_profiles = {}
        for name, profile in cfg["profiles"].items():
            if not isinstance(name, str):
                continue
            normalized = normalize_profile(profile, defaults)
            if normalized is not None:
                normalized_profiles[name] = normalized
        cfg["profiles"] = normalized_profiles

    return cfg


def save_config(cfg):
    # Atomic replace, so a crash or a concurrent writer (another vrgb run, a
    # frontend) never leaves a truncated file that load_config() would discard.
    # Keys this module does not know are kept, so frontends can store their own.
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_name(f".{CONFIG_FILE.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    if os.geteuid() == 0:
        # Elevated (sudo/pkexec) run: keep the file owned by the real user.
        try:
            st = CONFIG_DIR.stat()
            os.chown(tmp, st.st_uid, st.st_gid)
        except OSError:
            pass
    os.replace(tmp, CONFIG_FILE)


# Config semantics:
#   color            -> saved static RGB hex used for host/manual restore
#   percent          -> current intended brightness, may be 0 after `off`
#   last_on_percent  -> last known non-zero brightness for restore behavior
#   autonomous       -> whether firmware/autonomous mode should be preserved
#   profiles         -> named snapshots of color / percent / autonomous
#   cycle            -> {period, fps, pid} while the software rainbow is the saved
#                       mode; `restore` resumes it. Commands that set another
#                       mode remove it; `off` and `brightness` keep it.

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


# ===== Kernel Modules =====


def module_loaded(name: str) -> bool:
    # Linux exposes module names under /sys/module with hyphens converted to underscores.
    # Example: asus-nb-wmi -> /sys/module/asus_nb_wmi
    return Path(f"/sys/module/{name.replace('-', '_')}").exists()


def ensure_required_modules(devinfo):
    missing = [
        module
        for module in devinfo.get("required_modules", [])
        if not module_loaded(module)
    ]

    if not missing:
        return

    mods = " ".join(missing)
    first = missing[0]

    die(
        "Required kernel module missing: "
        + ", ".join(missing)
        + "\n\nThis device may ignore HID LampArray commands until the module is loaded."
        + "\n\nLoad once:\n"
        + f"  sudo modprobe {mods}"
        + "\n\nLoad at boot:\n"
        + f"  echo {first} | sudo tee /etc/modules-load.d/{first}.conf"
    )


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
        profile = None
        report_ids = read_lamparray_report_ids(dev)

        if hid_id in SUPPORTED_DEVICES:
            profile = SUPPORTED_DEVICES[hid_id]
            score = 100
            reason = "exact HID_ID match"
        else:
            for supported_hid_id, supported in SUPPORTED_DEVICES.items():
                if hid_name == supported["hid_name"]:
                    profile = supported
                    score = 90
                    reason = f"exact HID_NAME match ({supported_hid_id})"
                    break

        if profile is None and {
            LAMPARRAY_RANGE_UPDATE_REPORT,
            LAMPARRAY_CONTROL_REPORT,
            LAMPARRAY_ATTRIBUTES_REPORT,
        } <= report_ids.keys():
            profile = {"model": f"Unverified HID LampArray device ({hid_name})"}
            score = 50
            reason = "HID LampArray report descriptor"

        debug(
            f"{dev.name}: hid_id={hid_id} hid_name={hid_name} "
            f"score={score} reason={reason}"
        )

        if score > best_score and profile is not None:
            best_score = score
            best_reason = reason
            best_match = {
                "path": f"/dev/{dev.name}",
                "hid_id": hid_id,
                "hid_name": hid_name,
                "model": profile["model"],
                "confirmed_models": profile.get("confirmed_models", []),
                "firmware_report_id": report_ids.get(
                    LAMPARRAY_CONTROL_REPORT, profile.get("firmware_report_id")
                ),
                "color_report_id": report_ids.get(
                    LAMPARRAY_RANGE_UPDATE_REPORT, profile.get("color_report_id")
                ),
                "attributes_report_id": report_ids.get(LAMPARRAY_ATTRIBUTES_REPORT),
                "verified": score >= 90,
                "required_modules": profile.get("required_modules", []),
            }

    if best_match:
        debug(f"Selected device: {best_match['path']} ({best_reason})")
        debug(
            "Using report IDs: "
            f"firmware=0x{best_match['firmware_report_id']:02X} "
            f"color=0x{best_match['color_report_id']:02X}"
        )
        debug(f"Matched model: {best_match['model']}")
        if best_match.get("required_modules"):
            debug("Required modules: " + ", ".join(best_match["required_modules"]))
        ensure_required_modules(best_match)
        if not best_match["verified"]:
            # Verified devices keep their tested lamp range; others light every lamp.
            best_match["lamp_id_end"] = max(get_lamp_count(best_match) - 1, 0)
        return best_match

    die("VRGB HID device not found")


def parse_lamparray_report_ids(descriptor):
    """Map LampArray report usages to report IDs in a HID report descriptor.

    A report's ID is the Report ID in effect at the first main item inside its
    collection, which holds whether the descriptor declares it before or after
    the collection's Usage.
    """
    ids = {}
    usage_page = report_id = 0
    usages = []       # local Usage items since the last main item
    collections = []  # (page, usage) of each open collection
    pos = 0

    while pos < len(descriptor):
        prefix = descriptor[pos]
        if prefix == 0xFE:  # long item: data size in the next byte
            pos += 3 + (descriptor[pos + 1] if pos + 1 < len(descriptor) else 0)
            continue
        size = (0, 1, 2, 4)[prefix & 0x03]
        value = int.from_bytes(descriptor[pos + 1 : pos + 1 + size], "little")
        tag = prefix & 0xFC
        pos += 1 + size

        if tag == 0x04:    # Usage Page
            usage_page = value
        elif tag == 0x84:  # Report ID
            report_id = value
        elif tag == 0x08:  # Usage (a 4-byte usage carries its own page)
            usages.append((value >> 16, value & 0xFFFF) if size == 4 else (usage_page, value))
        elif tag == 0xA0:  # Collection
            collections.append(usages[-1] if usages else None)
            usages = []
        elif tag == 0xC0:  # End Collection
            if collections:
                collections.pop()
        elif tag in (0x80, 0x90, 0xB0):  # Input / Output / Feature
            for entry in collections:
                if entry and entry[0] == LAMPARRAY_USAGE_PAGE and report_id:
                    ids.setdefault(entry[1], report_id)
            usages = []

    return ids


def read_lamparray_report_ids(hidraw_dir):
    try:
        descriptor = (hidraw_dir / "device" / "report_descriptor").read_bytes()
    except OSError as e:
        debug(f"{hidraw_dir.name}: cannot read report descriptor: {e}")
        return {}
    return parse_lamparray_report_ids(descriptor)


def hid_get_feature(dev_path, report_id, length):
    buf = bytearray(length + 1)
    buf[0] = report_id
    fd = os.open(dev_path, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.ioctl(fd, HIDIOCGFEATURE(len(buf)), buf)
    finally:
        os.close(fd)
    debug(f"hid_get_feature dev={dev_path} report=0x{report_id:02X} data={buf[1:].hex()}")
    return bytes(buf[1:])


def get_lamp_count(devinfo):
    # LampArrayAttributesReport starts with LampCount (uint16, little-endian).
    try:
        data = hid_get_feature(devinfo["path"], devinfo["attributes_report_id"], 22)
    except PermissionError:
        die(f"Permission denied opening {devinfo['path']} (are you in the vrgb group?)")
    except OSError as e:
        die(f"Could not read LampArray attributes from {devinfo['path']}: {e}")
    return int.from_bytes(data[:2], "little")


def hid_set_feature(dev_path, report_id, payload_bytes):
    buf = bytes([report_id]) + payload_bytes
    debug(
        f"hid_set_feature dev={dev_path} report=0x{report_id:02X} "
        f"payload={payload_bytes.hex()}"
    )
    fd = os.open(dev_path, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.ioctl(fd, HIDIOCSFEATURE(len(buf)), buf)
    finally:
        os.close(fd)


def set_firmware_mode(devinfo, enabled: bool):
    debug(f"set_firmware_mode enabled={enabled}")
    hid_set_feature(
        devinfo["path"],
        devinfo["firmware_report_id"],
        bytes([FIRMWARE_BYTE if enabled else HOST_BYTE]),
    )


def set_color(devinfo, r, g, b, intensity):
    debug(f"set_color r={r} g={g} b={b} intensity={intensity}")

    # LampRangeUpdateReport: flags (update complete), LampIdStart, LampIdEnd, RGBI.
    lamp_id_end = devinfo.get("lamp_id_end", 0)
    payload = bytes(
        [
            0x01,
            0x00,
            0x00,
            lamp_id_end & 0xFF,
            lamp_id_end >> 8,
            clamp(r, 0, 255),
            clamp(g, 0, 255),
            clamp(b, 0, 255),
            clamp(intensity, 0, 255),
        ]
    )

    hid_set_feature(devinfo["path"], devinfo["color_report_id"], payload)


# ===== Profiles =====


def normalize_profile_name(name):
    name = name.strip()
    if not name:
        die("Profile name cannot be empty")
    return name


def get_profiles(cfg):
    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict):
        cfg["profiles"] = {}
        profiles = cfg["profiles"]
    return profiles


def apply_profile(cfg, devinfo, profile, save=True):
    color = profile["color"]
    percent = clamp(int(profile["percent"]), 0, 100)
    autonomous = bool(profile["autonomous"])

    debug(f"apply_profile color={color} percent={percent} autonomous={autonomous}")

    cfg.pop("cycle", None)
    cfg["color"] = color
    cfg["percent"] = percent
    if percent > 0:
        cfg["last_on_percent"] = percent
    cfg["autonomous"] = autonomous

    if autonomous:
        set_firmware_mode(devinfo, True)
    else:
        r, g, b = hex_to_rgb(color)
        intensity = percent_to_intensity(percent)
        set_firmware_mode(devinfo, False)
        set_color(devinfo, r, g, b, intensity)

    if save:
        save_config(cfg)


def cmd_profile_save(cfg, name):
    name = normalize_profile_name(name)
    profiles = get_profiles(cfg)

    profiles[name] = {
        "color": cfg["color"],
        "percent": cfg["percent"],
        "autonomous": cfg["autonomous"],
    }

    save_config(cfg)
    print(f"Saved profile: {name}")


def cmd_profile_load(cfg, devinfo, name):
    name = normalize_profile_name(name)
    profiles = get_profiles(cfg)

    if name not in profiles:
        die(f"Profile not found: {name}")

    apply_profile(cfg, devinfo, profiles[name], save=True)
    print(f"Loaded profile: {name}")


def cmd_profile_list(cfg):
    profiles = get_profiles(cfg)

    if not profiles:
        print("No profiles saved.")
        return

    print("Profiles:")
    for name in sorted(profiles):
        print(f"  {name}")


def cmd_profile_delete(cfg, name):
    name = normalize_profile_name(name)
    profiles = get_profiles(cfg)

    if name not in profiles:
        die(f"Profile not found: {name}")

    del profiles[name]
    save_config(cfg)
    print(f"Deleted profile: {name}")


# ===== Commands =====


def cmd_about():
    print(
        r"""
                 _
__   ___ __ __ _| |__
\ \ / / '__/ _` | '_ \
 \ V /| | | (_| | |_) |
  \_/ |_|  \__, |_.__/
           |___/

Native RGB control for ASUS Vivobook keyboards on Linux

VRGB """
        + VERSION
        + """
"""
        + PROJECT_URL
        + """

Core CLI • Desktop Suite • HID LampArray
"""
    )


def cmd_status(cfg, devinfo):
    print("Device:", devinfo["path"])
    print("Model:", devinfo["model"])
    print("HID ID:", devinfo["hid_id"])
    if not devinfo.get("verified", True):
        print("Verified: no (detected from its HID LampArray descriptor; please report results)")

    confirmed_models = devinfo.get("confirmed_models", [])
    if confirmed_models:
        print("Confirmed on:", ", ".join(confirmed_models))

    required_modules = devinfo.get("required_modules", [])
    if required_modules:
        print("Required modules:", ", ".join(required_modules))

    print("Saved color:", "#" + cfg["color"])
    print("Saved brightness:", cfg["percent"], "%")
    print("Last-on brightness:", cfg["last_on_percent"], "%")
    cycle = cfg.get("cycle")
    if isinstance(cycle, dict):
        print(f"Saved mode: rainbow cycle (period={cycle.get('period')}s, {cycle.get('fps')} fps)")
    else:
        print("Saved mode:", "firmware/autonomous" if cfg["autonomous"] else "host/static")
    debug("status complete")


def cmd_set(cfg, devinfo, color, percent=None):
    r, g, b = hex_to_rgb(color)

    if percent is None:
        percent = cfg["percent"]

    percent = clamp(int(percent), 0, 100)
    intensity = percent_to_intensity(percent)
    debug(f"cmd_set color={color} percent={percent} intensity={intensity}")

    set_firmware_mode(devinfo, False)
    set_color(devinfo, r, g, b, intensity)

    cfg.pop("cycle", None)
    cfg["color"] = color.replace("#", "").lower()
    cfg["percent"] = percent
    if percent > 0:
        cfg["last_on_percent"] = percent
    cfg["autonomous"] = False
    save_config(cfg)


def cmd_brightness(cfg, devinfo, percent):
    r, g, b = hex_to_rgb(cfg["color"])

    percent = clamp(int(percent), 0, 100)
    intensity = percent_to_intensity(percent)
    debug(f"cmd_brightness percent={percent} intensity={intensity}")

    if cfg.get("cycle"):
        # A running cycle picks the new brightness up from the config.
        cfg["percent"] = percent
        if percent > 0:
            cfg["last_on_percent"] = percent
        save_config(cfg)
        return

    set_firmware_mode(devinfo, False)
    set_color(devinfo, r, g, b, intensity)

    cfg["percent"] = percent
    if percent > 0:
        cfg["last_on_percent"] = percent
    cfg["autonomous"] = False
    save_config(cfg)


def cmd_auto(cfg, devinfo, state):
    firmware_on = state == "on"
    debug(f"cmd_auto state={state}")
    cfg.pop("cycle", None)

    if firmware_on:
        set_firmware_mode(devinfo, True)
        cfg["autonomous"] = True
        save_config(cfg)
    else:
        r, g, b, p, intensity = get_saved_static_state(cfg)
        debug(f"cmd_auto off -> restore percent={p} intensity={intensity}")
        set_firmware_mode(devinfo, False)
        set_color(devinfo, r, g, b, intensity)
        cfg["percent"] = p
        cfg["autonomous"] = False
        save_config(cfg)


def owns_cycle(cfg):
    cycle = cfg.get("cycle")
    return isinstance(cycle, dict) and cycle.get("pid") == os.getpid() and cfg["percent"] > 0


def config_stamp():
    # Every save replaces the file, so a new inode marks a write even within one mtime tick.
    try:
        st = CONFIG_FILE.stat()
        return st.st_ino, st.st_mtime_ns
    except FileNotFoundError:
        return None


def hand_over(cfg, devinfo):
    """Re-apply the state another command saved: this process's last frame may
    have reached the keyboard after that command's own write."""
    cycle = cfg.get("cycle")
    if isinstance(cycle, dict) and cfg["percent"] > 0:
        return  # a newer cycle drives the keyboard now
    if cfg["autonomous"]:
        set_firmware_mode(devinfo, True)
    else:
        r, g, b = hex_to_rgb(cfg["color"])
        set_firmware_mode(devinfo, False)
        set_color(devinfo, r, g, b, percent_to_intensity(cfg["percent"]))


RESTORE_SERVICE = "vrgb-restore.service"
# `vrgb rainbow` with no argument: the software cycle at these settings.
RAINBOW_PERCENT = 100
RAINBOW_PERIOD = 4


def cmd_cycle(cfg, devinfo, percent=None, period=None, fps=None):
    save_cycle(cfg, percent, period, fps)
    run_cycle(cfg, devinfo)


def start_cycle_service():
    """Hand the saved cycle to the user's restore service, so it keeps running
    without a terminal. Returns False when that service is not enabled."""
    try:
        enabled = subprocess.run(
            ["systemctl", "--user", "--quiet", "is-enabled", RESTORE_SERVICE]
        ).returncode == 0
        if not enabled:
            return False
        return subprocess.run(["systemctl", "--user", "restart", RESTORE_SERVICE]).returncode == 0
    except OSError:  # no systemctl
        return False


def save_cycle(cfg, percent=None, period=None, fps=None):
    if percent is None:
        percent = cfg["percent"] or cfg["last_on_percent"]
    if period is None:
        period = 6.0
    if fps is None:
        fps = 20.0

    try:
        percent = clamp(int(percent), 0, 100)
    except (TypeError, ValueError):
        die("percent must be a whole number from 0 to 100 (example: 50)")

    try:
        period = float(period)
        fps = float(fps)
    except (TypeError, ValueError):
        die("period and fps must be numbers")

    if percent <= 0:
        die("percent must be greater than 0")
    if period <= 0:
        die("period must be greater than 0")
    if fps <= 0:
        die("fps must be greater than 0")

    debug(f"cmd_cycle percent={percent} period={period} fps={fps}")

    # Saving the cycle makes it the restored mode, and tells an older cycle
    # process (whose pid no longer matches) to stop.
    cfg["cycle"] = {"period": period, "fps": fps, "pid": os.getpid()}
    cfg["percent"] = percent
    cfg["last_on_percent"] = percent
    cfg["autonomous"] = False
    save_config(cfg)


def run_cycle(cfg, devinfo):
    period, fps = cfg["cycle"]["period"], cfg["cycle"]["fps"]
    stamp = config_stamp()

    print(f"Cycling through the color spectrum (period={period}s, {fps} fps). Press Ctrl+C to stop.")

    frame_delay = 1.0 / fps
    start = time.monotonic()

    try:
        set_firmware_mode(devinfo, False)
        while True:
            if config_stamp() != stamp:
                stamp = config_stamp()
                cfg = load_config()
                if not owns_cycle(cfg):
                    debug("cmd_cycle config changed by another command; stopping")
                    hand_over(cfg, devinfo)
                    return
            try:
                hue = ((time.monotonic() - start) / period) % 1.0
                r, g, b = (round(c * 255) for c in colorsys.hsv_to_rgb(hue, 1.0, 1.0))
                set_color(devinfo, r, g, b, percent_to_intensity(cfg["percent"]))
            except OSError as e:
                # The hidraw node can briefly disappear or re-enumerate
                # around suspend/resume; reacquire it and keep cycling.
                debug(f"cmd_cycle lost device ({e}); reacquiring")
                time.sleep(1.0)
                devinfo = find_device()
                set_firmware_mode(devinfo, False)
                continue
            time.sleep(frame_delay)
    except KeyboardInterrupt:
        # Ctrl+C is a deliberate stop, so the cycle is not resumed at the next login.
        cfg = load_config()
        if owns_cycle(cfg):
            cfg.pop("cycle")
            save_config(cfg)
        print("\nStopped cycling.")


def cmd_off(cfg, devinfo):
    r, g, b = hex_to_rgb(cfg["color"])
    debug("cmd_off")

    p = int(cfg.get("percent", 100))
    if p > 0:
        cfg["last_on_percent"] = p

    set_firmware_mode(devinfo, False)
    set_color(devinfo, r, g, b, 0)

    cfg["percent"] = 0
    cfg["autonomous"] = False
    save_config(cfg)


def cmd_restore(cfg, devinfo):
    if cfg.get("autonomous", False):
        debug("cmd_restore autonomous=True -> keep firmware mode")
        set_firmware_mode(devinfo, True)
        return

    r, g, b, p, intensity = get_saved_static_state(cfg)
    debug(f"cmd_restore percent={p} intensity={intensity}")

    set_firmware_mode(devinfo, False)
    set_color(devinfo, r, g, b, intensity)

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
        print(
            """Usage:
  vrgb status
  vrgb set RRGGBB [percent]
  vrgb brightness 0-100
  vrgb auto on|off
  vrgb rainbow             (software rainbow: cycle 100 4)
  vrgb cycle [percent] [period_seconds] [fps]
  vrgb off
  vrgb restore
  vrgb profile save NAME
  vrgb profile load NAME
  vrgb profile list
  vrgb profile delete NAME
  vrgb about

----------------------------------------
Tip: use --debug before the command for diagnostic output
Example: vrgb --debug status
"""
        )
        sys.exit(1)

    cfg = load_config()
    cmd = args[0]

    known_commands = {
        "status",
        "set",
        "brightness",
        "auto",
        "rainbow",
        "cycle",
        "off",
        "restore",
        "profile",
        "about",
    }

    if cmd not in known_commands:
        die("Unknown command")

    if cmd == "status":
        devinfo = find_device()
        cmd_status(cfg, devinfo)

    elif cmd == "set":
        if len(args) < 2:
            die("Missing color")
        devinfo = find_device()
        percent = args[2] if len(args) > 2 else None
        cmd_set(cfg, devinfo, args[1], percent)

    elif cmd == "brightness":
        if len(args) < 2:
            die("Missing percent")
        devinfo = find_device()
        cmd_brightness(cfg, devinfo, args[1])

    elif cmd == "auto":
        if len(args) < 2 or args[1] not in ["on", "off"]:
            die("auto requires 'on' or 'off'")
        devinfo = find_device()
        cmd_auto(cfg, devinfo, args[1])

    elif cmd == "cycle" or args == ["rainbow"]:
        devinfo = find_device()
        if cmd == "rainbow":
            percent, period, fps = RAINBOW_PERCENT, RAINBOW_PERIOD, None
        else:
            percent = args[1] if len(args) > 1 else None
            period = args[2] if len(args) > 2 else None
            fps = args[3] if len(args) > 3 else None
        save_cycle(cfg, percent, period, fps)
        if start_cycle_service():
            print(f"Rainbow cycle running in the background ({RESTORE_SERVICE}).")
        else:
            run_cycle(cfg, devinfo)

    elif cmd == "off":
        devinfo = find_device()
        cmd_off(cfg, devinfo)

    elif cmd == "restore":
        devinfo = find_device()
        cycle = cfg.get("cycle")
        if isinstance(cycle, dict):
            p = get_saved_static_state(cfg)[3]
            cmd_cycle(cfg, devinfo, p, cycle.get("period"), cycle.get("fps"))
        else:
            cmd_restore(cfg, devinfo)

    elif cmd == "profile":
        if len(args) < 2:
            die("profile requires a subcommand: save, load, list, or delete")

        subcmd = args[1]

        if subcmd == "save":
            if len(args) < 3:
                die("profile save requires a name")
            cmd_profile_save(cfg, args[2])
        elif subcmd == "load":
            if len(args) < 3:
                die("profile load requires a name")
            devinfo = find_device()
            cmd_profile_load(cfg, devinfo, args[2])
        elif subcmd == "list":
            cmd_profile_list(cfg)
        elif subcmd == "delete":
            if len(args) < 3:
                die("profile delete requires a name")
            cmd_profile_delete(cfg, args[2])
        else:
            die("profile requires a subcommand: save, load, list, or delete")

    elif cmd == "about":
        cmd_about()

    else:
        die("Unknown command")


def run():
    """Console entry point (also used by packaged installs)."""
    try:
        main()
    except PermissionError:
        die("Permission denied to HID device. Run with sudo or install a udev rule.")


if __name__ == "__main__":
    run()
