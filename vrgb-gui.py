#!/usr/bin/env python3
"""
VRGB GUI — a PyQt6 frontend for the `vrgb` CLI (ASUS Vivobook ITE5570 RGB keyboards).

Design:
  * The GUI imports the installed `vrgb` script as a module (importlib) and calls its
    functions in-process for low-latency control of the keyboard. This reuses the exact
    HID protocol, report-id mapping and config logic from the CLI — no duplication.
  * All device I/O happens on a dedicated worker thread so the UI never blocks.
  * If opening the hidraw device raises PermissionError (e.g. the user is in the `vrgb`
    group but has not logged out/in yet, so the group is not active in this session),
    persisting actions fall back to `pkexec vrgb ...`, which prompts for a password via
    Polkit and runs as root. Live "preview" drags are best-effort and silently skipped
    in that case (to avoid password spam) until the group is active.

    The pkexec fallback ONLY ever runs the root-owned /usr/local/bin/vrgb binary; it
    never runs a user-writable script as root. The CLI honours PKEXEC_UID so the
    elevated run reads/writes the invoking user's ~/.config/vrgb, not /root's.

Unified brightness:
  The ASUS keyboard has TWO brightness layers that multiply:
    * the firmware backlight (FN+F4 / FN+F3) -> /sys/class/leds/asus::kbd_backlight,
      a coarse 0..max (max=3) level set via logind (passwordless for the active session);
    * vrgb's HID "intensity" byte (0..255), the fine per-color scaling.
  The slider exposes a single unified brightness B (0..100%). It is decomposed into a
  firmware step F and an HID intensity I such that (F/max) * (I/255) == B, so the two
  layers never double-dim. The firmware level is polled, so FN+F4/F3 move the slider
  (and the HID intensity) too. If the LED node or logind is unavailable the GUI falls
  back to pure-HID brightness (B == I).

State (color / intensity / profiles / autonomous) lives in ~/.config/vrgb/config.json,
read through the imported module's load_config().
"""

import sys
import os
import math
import copy
import time
import queue
import subprocess
import importlib.util
import importlib.machinery
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QPointF
from PyQt6.QtGui import (
    QColor,
    QConicalGradient,
    QRadialGradient,
    QPainter,
    QPen,
    QBrush,
    QIcon,
    QPixmap,
    QAction,
    QActionGroup,
)
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QSlider,
    QPushButton,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
    QGroupBox,
    QInputDialog,
    QMessageBox,
    QSystemTrayIcon,
    QMenu,
    QSizePolicy,
    QFrame,
    QWidgetAction,
    QColorDialog,
)


# ----------------------------------------------------------------------------
# Locate + import the vrgb core script as a module
# ----------------------------------------------------------------------------

def _core_candidates():
    here = Path(__file__).resolve().parent
    return [
        Path("/usr/local/bin/vrgb"),   # installed CLI (preferred)
        here / "vrgb.py",              # running from the repo checkout
    ]


def load_core():
    for path in _core_candidates():
        if path.exists():
            loader = importlib.machinery.SourceFileLoader("vrgb_core", str(path))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            mod = importlib.util.module_from_spec(spec)
            loader.exec_module(mod)   # main() is guarded by __name__ == "__main__"
            return mod, path
    raise FileNotFoundError(
        "Could not find the vrgb core script. Install it (./install.sh) or run the GUI "
        "from the repository checkout next to vrgb.py."
    )


def pkexec_target():
    """A SAFE root-owned binary to run under pkexec, or None.

    Running a user-writable file as root is a local privilege-escalation primitive,
    so we require /usr/local/bin/vrgb to exist, be owned by root, and not be group-
    or world-writable. We never fall back to the (user-owned) repo checkout.
    """
    p = Path("/usr/local/bin/vrgb")
    try:
        st = p.stat()
    except OSError:
        return None
    if st.st_uid != 0:
        return None
    if st.st_mode & 0o022:          # group/other writable -> unsafe
        return None
    return str(p)


# ----------------------------------------------------------------------------
# Firmware keyboard backlight (FN+F4 / FN+F3) via logind
# ----------------------------------------------------------------------------

class KbdBacklight:
    """Reads/writes /sys/class/leds/asus::kbd_backlight.

    Reads come straight from sysfs (world-readable). Writes go through logind's
    SetBrightness, which Polkit allows for the active local session without a
    password. Returns gracefully degraded values when the node is absent.
    """

    PATH = Path("/sys/class/leds/asus::kbd_backlight")
    LED_NAME = "asus::kbd_backlight"

    def __init__(self):
        self.available = self.PATH.exists()
        self.max = (self._read_int("max_brightness") or 0) if self.available else 0
        if self.max <= 0:
            self.available = False

    def _read_int(self, name):
        try:
            return int((self.PATH / name).read_text().strip())
        except (OSError, ValueError):
            return None

    def level(self):
        return self._read_int("brightness")

    @staticmethod
    def set_level(level):
        try:
            subprocess.run(
                ["busctl", "call", "org.freedesktop.login1",
                 "/org/freedesktop/login1/session/auto",
                 "org.freedesktop.login1.Session", "SetBrightness", "ssu",
                 "leds", KbdBacklight.LED_NAME, str(int(level))],
                check=True, capture_output=True, text=True, timeout=10,
            )
            return True
        except Exception:
            return False


# ----------------------------------------------------------------------------
# Login autostart (~/.config/autostart) — user-managed, no root needed
# ----------------------------------------------------------------------------

class Autostart:
    """Create/remove the per-user XDG autostart .desktop entries.

    Two independent entries:
      * 'restore' -> reapply the saved lighting at login (`vrgb restore`)
      * 'tray'    -> start the GUI minimised to the tray (`vrgb-gui --tray`)
    """

    DIR = Path.home() / ".config" / "autostart"
    ENTRIES = {
        "restore": {
            "file": "vrgb.desktop",
            "name": "VRGB Restore",
            "comment": "Restore keyboard RGB state on login",
            "exec": "/usr/local/bin/vrgb restore",
            "icon": "vrgb",
        },
        "tray": {
            "file": "vrgb-gui.desktop",
            "name": "VRGB (tray)",
            "comment": "Keyboard RGB control tray applet",
            "exec": "/usr/local/bin/vrgb-gui --tray",
            "icon": "vrgb",
        },
    }

    @classmethod
    def path(cls, key):
        return cls.DIR / cls.ENTRIES[key]["file"]

    @classmethod
    def is_enabled(cls, key):
        p = cls.path(key)
        if not p.exists():
            return False
        try:
            low = p.read_text(errors="ignore").lower()
        except OSError:
            return False
        if "hidden=true" in low:
            return False
        if "x-gnome-autostart-enabled=false" in low:
            return False
        return True

    @classmethod
    def set_enabled(cls, key, enabled):
        p = cls.path(key)
        if enabled:
            e = cls.ENTRIES[key]
            cls.DIR.mkdir(parents=True, exist_ok=True)
            p.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                f"Name={e['name']}\n"
                f"Comment={e['comment']}\n"
                f"Exec={e['exec']}\n"
                f"Icon={e['icon']}\n"
                "Terminal=false\n"
                "X-GNOME-Autostart-enabled=true\n"
            )
        else:
            try:
                p.unlink()
            except FileNotFoundError:
                pass


# ----------------------------------------------------------------------------
# Worker thread: serializes all device I/O off the UI thread
# ----------------------------------------------------------------------------

class DeviceWorker(QThread):
    op_done = pyqtSignal(str, bool, str)        # op name, ok, human message
    device_status = pyqtSignal(object, str)     # devinfo dict or None, error message
    config_updated = pyqtSignal(dict)           # fresh config snapshot

    def __init__(self, mod, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.pkexec_bin = pkexec_target()
        self.q: "queue.Queue" = queue.Queue()
        self._devinfo = None
        self._running = True
        self._proc = None  # tracked pkexec subprocess, for shutdown

    # -- public API (called from the UI thread) --
    def submit(self, op, *args):
        self.q.put((op, args))

    def stop(self):
        self._running = False
        p = self._proc
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass
        self.q.put(("quit", ()))

    # -- internals (run on the worker thread) --
    def run(self):
        while self._running:
            try:
                op, args = self.q.get(timeout=0.25)
            except queue.Empty:
                continue
            if op == "quit":
                break
            try:
                self._dispatch(op, args)
            except Exception as exc:  # never let the worker die
                self.op_done.emit(op, False, f"{type(exc).__name__}: {exc}")

    def _ensure_device(self):
        if self._devinfo is not None:
            return self._devinfo
        try:
            self._devinfo = self.mod.find_device()
            self.device_status.emit(self._devinfo, "")
        except SystemExit:
            self.device_status.emit(None, "VRGB keyboard not found")
            raise
        return self._devinfo

    def _cfg(self):
        return self.mod.load_config()

    def _emit_cfg(self, cfg):
        snap = dict(cfg)
        snap["profiles"] = copy.deepcopy(cfg.get("profiles", {}))
        self.config_updated.emit(snap)

    def _run_cli(self, cli_args):
        """Privileged fallback via pkexec (Polkit GUI password prompt)."""
        if not self.pkexec_bin:
            raise RuntimeError(
                "Privileged fallback unavailable: install the vrgb CLI to "
                "/usr/local/bin (run ./install.sh), then log out and back in."
            )
        self._proc = subprocess.Popen(
            ["pkexec", self.pkexec_bin, *cli_args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            out, err = self._proc.communicate(timeout=120)
            rc = self._proc.returncode
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.communicate()
            raise RuntimeError("pkexec timed out waiting for authorization")
        finally:
            self._proc = None
        if rc != 0:
            raise RuntimeError((err or out or "pkexec failed").strip())

    # -- per-op handlers --
    def _dispatch(self, op, args):
        handler = getattr(self, f"_op_{op}", None)
        if handler is None:
            self.op_done.emit(op, False, f"unknown op '{op}'")
            return
        handler(self.mod, *args)

    def _op_detect(self, mod):
        try:
            self._ensure_device()
        except SystemExit:
            pass

    def _op_fwlevel(self, mod, level):
        if not KbdBacklight.set_level(level):
            self.op_done.emit("fwlevel", False, "Could not set keyboard backlight level")

    def _op_color(self, mod, hexcol, percent, persist):
        try:
            dev = self._ensure_device()
        except SystemExit:
            return
        try:
            if persist:
                cfg = self._cfg()
                mod.cmd_set(cfg, dev, hexcol, str(percent))
                self._emit_cfg(cfg)
                self.op_done.emit("color", True, f"Set #{hexcol}")
            else:
                r, g, b = mod.hex_to_rgb(hexcol)
                intensity = mod.percent_to_intensity(percent)
                mod.set_firmware_mode(dev, False)
                mod.set_color(dev, r, g, b, intensity)
        except PermissionError:
            if persist:
                self._run_cli(["set", hexcol, str(percent)])
                self._emit_cfg(self._cfg())
                self.op_done.emit("color", True, f"Set #{hexcol} (pkexec)")

    def _op_power(self, mod, on):
        try:
            dev = self._ensure_device()
        except SystemExit:
            return
        cfg = self._cfg()
        try:
            if on:
                mod.cmd_restore(cfg, dev)
            else:
                mod.cmd_off(cfg, dev)
            self._emit_cfg(cfg)
            self.op_done.emit("power", True, "On" if on else "Off")
        except PermissionError:
            self._run_cli(["restore" if on else "off"])
            self._emit_cfg(self._cfg())
            self.op_done.emit("power", True, ("On" if on else "Off") + " (pkexec)")

    def _op_auto(self, mod, on):
        try:
            dev = self._ensure_device()
        except SystemExit:
            return
        cfg = self._cfg()
        try:
            mod.cmd_auto(cfg, dev, "on" if on else "off")
            self._emit_cfg(cfg)
            self.op_done.emit("auto", True, "Firmware mode " + ("on" if on else "off"))
        except PermissionError:
            self._run_cli(["auto", "on" if on else "off"])
            self._emit_cfg(self._cfg())
            self.op_done.emit("auto", True, "Firmware mode " + ("on" if on else "off") + " (pkexec)")

    def _op_rainbow(self, mod, on):
        try:
            dev = self._ensure_device()
        except SystemExit:
            return
        cfg = self._cfg()
        try:
            mod.cmd_rainbow(cfg, dev, "on" if on else "off")
            self._emit_cfg(cfg)
            self.op_done.emit("rainbow", True, "Rainbow " + ("on" if on else "off"))
        except PermissionError:
            self._run_cli(["rainbow", "on" if on else "off"])
            self._emit_cfg(self._cfg())
            self.op_done.emit("rainbow", True, "Rainbow " + ("on" if on else "off") + " (pkexec)")
        except SystemExit:
            self.op_done.emit("rainbow", False, "OEM rainbow not supported on this device")

    def _op_profile_save(self, mod, name):
        cfg = self._cfg()
        mod.cmd_profile_save(cfg, name)
        self._emit_cfg(cfg)
        self.op_done.emit("profile_save", True, f"Saved profile '{name}'")

    def _op_profile_delete(self, mod, name):
        cfg = self._cfg()
        try:
            mod.cmd_profile_delete(cfg, name)
            self._emit_cfg(cfg)
            self.op_done.emit("profile_delete", True, f"Deleted profile '{name}'")
        except SystemExit:
            self.op_done.emit("profile_delete", False, f"Profile '{name}' not found")

    def _op_profile_load(self, mod, name):
        try:
            dev = self._ensure_device()
        except SystemExit:
            return
        cfg = self._cfg()
        try:
            mod.cmd_profile_load(cfg, dev, name)
            self._emit_cfg(cfg)
            self.op_done.emit("profile_load", True, f"Loaded profile '{name}'")
        except PermissionError:
            self._run_cli(["profile", "load", name])
            self._emit_cfg(self._cfg())
            self.op_done.emit("profile_load", True, f"Loaded profile '{name}' (pkexec)")
        except SystemExit:
            self.op_done.emit("profile_load", False, f"Profile '{name}' not found")


# ----------------------------------------------------------------------------
# HS color wheel widget
# ----------------------------------------------------------------------------

class ColorWheel(QWidget):
    """Hue/Saturation wheel. Value (lightness) is supplied externally."""

    hs_changed = pyqtSignal(float, float)   # hue 0..1, saturation 0..1
    released = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._h = 0.0
        self._s = 0.0
        self._value = 1.0
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_hsv(self, h, s, v):
        self._h, self._s, self._value = h, s, v
        self.update()

    def set_value(self, v):
        self._value = v
        self.update()

    def _geom(self):
        side = min(self.width(), self.height()) - 8
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        return cx, cy, side / 2.0

    def paintEvent(self, _evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, r = self._geom()
        if r <= 0:
            return
        center = QPointF(cx, cy)

        hue_grad = QConicalGradient(center, 0.0)
        for i in range(0, 361, 30):
            hue_grad.setColorAt(i / 360.0, QColor.fromHsvF((i % 360) / 360.0, 1.0, 1.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(hue_grad))
        p.drawEllipse(center, r, r)

        sat_grad = QRadialGradient(center, r)
        sat_grad.setColorAt(0.0, QColor(255, 255, 255, 255))
        sat_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(sat_grad))
        p.drawEllipse(center, r, r)

        if self._value < 1.0:
            shade = int((1.0 - self._value) * 255)
            p.setBrush(QColor(0, 0, 0, shade))
            p.drawEllipse(center, r, r)

        angle = self._h * 2.0 * math.pi
        dist = self._s * r
        mx = cx + dist * math.cos(angle)
        my = cy - dist * math.sin(angle)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 200), 3))
        p.drawEllipse(QPointF(mx, my), 8, 8)
        p.setPen(QPen(QColor(255, 255, 255, 230), 1.5))
        p.drawEllipse(QPointF(mx, my), 8, 8)

    def _pick(self, pos):
        cx, cy, r = self._geom()
        if r <= 0:
            return
        dx = pos.x() - cx
        dy = cy - pos.y()
        dist = math.hypot(dx, dy)
        self._s = min(1.0, dist / r)
        ang = math.atan2(dy, dx)
        if ang < 0:
            ang += 2.0 * math.pi
        self._h = ang / (2.0 * math.pi)
        self.update()
        self.hs_changed.emit(self._h, self._s)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._pick(e.position())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._pick(e.position())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.released.emit()


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

PRESETS = [
    ("Red", "ff0000"), ("Orange", "ff6a00"), ("Yellow", "ffd400"),
    ("Green", "00ff44"), ("Cyan", "00e5ff"), ("Blue", "0066ff"),
    ("Purple", "aa00ff"), ("Magenta", "ff00aa"), ("White", "ffffff"),
]


def make_logo_icon():
    for cand in ("/usr/share/pixmaps/vrgb.png",
                 str(Path(__file__).resolve().parent / "assets" / "vrgblogodark.png")):
        if os.path.exists(cand):
            ic = QIcon(cand)
            if not ic.isNull():
                return ic
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QConicalGradient(32, 32, 0)
    for i in range(0, 361, 30):
        grad.setColorAt(i / 360.0, QColor.fromHsvF((i % 360) / 360.0, 1.0, 1.0))
    p.setPen(QPen(QBrush(grad), 10))
    p.drawEllipse(10, 10, 44, 44)
    p.end()
    return QIcon(pm)


def swatch_icon(hexc):
    pm = QPixmap(16, 16)
    pm.fill(QColor("#" + hexc))
    return QIcon(pm)


# ----------------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, worker: DeviceWorker, mod):
        super().__init__()
        self.worker = worker
        self.mod = mod
        self.kbd = KbdBacklight()
        self._suppress = False           # block feedback loops while we set widgets
        self._interacting = False        # user dragging a control
        self._devinfo = None
        self._preset_btns = []
        self._dev_widgets = []

        # Unified-brightness state
        self._brightness_b = 100         # slider value (unified 0..100)
        self._percent = 100              # HID intensity % sent to vrgb
        self._expected_fw = self.kbd.level() if self.kbd.available else None
        self._fw_ignore_until = 0.0      # monotonic deadline to ignore self-induced fw changes

        self.setWindowTitle("VRGB — Keyboard RGB")
        self.setWindowIcon(make_logo_icon())

        cfg = mod.load_config()
        self._color = QColor("#" + cfg.get("color", "aa00ff"))

        self._build_ui()
        self._wire_worker()

        self._preview = QTimer(self)
        self._preview.setSingleShot(True)
        self._preview.setInterval(45)
        self._preview.timeout.connect(self._emit_preview)
        self._pending = None             # (hex, hid_percent)

        self._load_from_cfg(cfg)
        self._load_autostart_state()

        # Poll the firmware backlight so FN+F4/F3 move the slider too.
        if self.kbd.available:
            self._fw_timer = QTimer(self)
            self._fw_timer.setInterval(300)
            self._fw_timer.timeout.connect(self._poll_firmware)
            self._fw_timer.start()

        self.worker.submit("detect")

    # ---- unified brightness math ----
    def _levels_for(self, b):
        """Unified brightness B (0..100) -> (firmware_level | None, hid_percent)."""
        b = max(0, min(100, int(round(b))))
        if not self.kbd.available:
            return None, b                       # pure HID
        if b <= 0:
            return 0, 0
        maxf = self.kbd.max
        f = max(1, math.ceil(b / 100.0 * maxf))  # smallest fw step that can reach b
        i = min(100, int(round(b * maxf / f)))   # HID fills the gap: (f/maxf)*(i/100)=b/100
        return f, i

    def _b_from(self, fw_level, hid_percent):
        if not self.kbd.available or fw_level is None:
            return int(round(hid_percent))
        return int(round(fw_level * hid_percent / self.kbd.max))

    def _set_firmware(self, level):
        self._expected_fw = level
        self._fw_ignore_until = time.monotonic() + 0.6
        self.worker.submit("fwlevel", level)

    # -- UI construction --
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        self.status_lbl = QLabel("Detecting keyboard…")
        self.status_lbl.setStyleSheet("color:#999;")
        root.addWidget(self.status_lbl)

        color_box = QGroupBox("Color")
        cgrid = QGridLayout(color_box)

        self.wheel = ColorWheel()
        cgrid.addWidget(self.wheel, 0, 0, 4, 1)

        self.value_slider = QSlider(Qt.Orientation.Vertical)
        self.value_slider.setRange(0, 100)
        self.value_slider.setValue(100)
        self.value_slider.setToolTip("Value (color lightness)")
        cgrid.addWidget(self.value_slider, 0, 1, 4, 1)

        self.swatch = QFrame()
        self.swatch.setMinimumSize(64, 64)
        self.swatch.setFrameShape(QFrame.Shape.StyledPanel)
        cgrid.addWidget(self.swatch, 0, 2)

        cgrid.addWidget(QLabel("Hex"), 1, 2)
        self.hex_edit = QLineEdit()
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setPlaceholderText("#rrggbb")
        cgrid.addWidget(self.hex_edit, 2, 2)

        preset_row = QHBoxLayout()
        for name, hexc in PRESETS:
            b = QPushButton()
            b.setFixedSize(24, 24)
            b.setToolTip(name)
            b.setStyleSheet(f"background:#{hexc}; border:1px solid #444; border-radius:4px;")
            b.clicked.connect(lambda _=False, h=hexc: self._apply_hex("#" + h, commit=True))
            preset_row.addWidget(b)
            self._preset_btns.append(b)
        preset_row.addStretch(1)
        cgrid.addLayout(preset_row, 4, 0, 1, 3)

        root.addWidget(color_box)

        bbox = QGroupBox("Brightness & power")
        bl = QGridLayout(bbox)
        self.power_btn = QPushButton("Power")
        self.power_btn.setCheckable(True)
        self.power_btn.setMinimumWidth(90)
        bl.addWidget(self.power_btn, 0, 0, 2, 1)

        bl.addWidget(QLabel("Brightness"), 0, 1)
        self.bright_slider = QSlider(Qt.Orientation.Horizontal)
        self.bright_slider.setRange(0, 100)
        self.bright_slider.setValue(self._brightness_b)
        if self.kbd.available:
            self.bright_slider.setToolTip("Unified brightness — also moves with FN+F4 / FN+F3")
        bl.addWidget(self.bright_slider, 0, 2)
        self.bright_lbl = QLabel(f"{self._brightness_b}%")
        self.bright_lbl.setMinimumWidth(40)
        bl.addWidget(self.bright_lbl, 0, 3)

        self.auto_chk = QCheckBox("Firmware / autonomous mode")
        self.auto_chk.setToolTip("Hand control back to the keyboard firmware")
        bl.addWidget(self.auto_chk, 1, 1, 1, 2)

        self.rainbow_chk = QCheckBox("OEM rainbow")
        bl.addWidget(self.rainbow_chk, 1, 3)

        root.addWidget(bbox)

        pbox = QGroupBox("Profiles")
        pl = QGridLayout(pbox)
        self.profile_list = QListWidget()
        self.profile_list.setMaximumHeight(110)
        pl.addWidget(self.profile_list, 0, 0, 4, 1)
        self.btn_load = QPushButton("Load")
        self.btn_save = QPushButton("Save current…")
        self.btn_delete = QPushButton("Delete")
        pl.addWidget(self.btn_save, 0, 1)
        pl.addWidget(self.btn_load, 1, 1)
        pl.addWidget(self.btn_delete, 2, 1)
        root.addWidget(pbox)

        sbox = QGroupBox("Start at login")
        sgl = QVBoxLayout(sbox)
        self.auto_restore_chk = QCheckBox("Restore my lighting at login")
        self.auto_restore_chk.setToolTip("Runs `vrgb restore` on login (color can reset on a full power cycle)")
        self.auto_tray_chk = QCheckBox("Start the tray icon at login")
        self.auto_tray_chk.setToolTip("Launches this app minimised to the system tray on login")
        sgl.addWidget(self.auto_restore_chk)
        sgl.addWidget(self.auto_tray_chk)
        root.addWidget(sbox)

        self.setCentralWidget(central)

        self._dev_widgets = [
            self.wheel, self.value_slider, self.hex_edit,
            self.bright_slider, self.power_btn, self.auto_chk,
        ] + self._preset_btns

        # Signal wiring
        self.wheel.hs_changed.connect(self._on_wheel)
        self.wheel.released.connect(self._commit_color)
        self.value_slider.valueChanged.connect(self._on_value)
        self.value_slider.sliderReleased.connect(self._commit_color)
        self.hex_edit.editingFinished.connect(lambda: self._apply_hex(self.hex_edit.text(), commit=True))
        self.bright_slider.valueChanged.connect(self._on_brightness)
        self.bright_slider.sliderReleased.connect(self._commit_color)
        self.power_btn.clicked.connect(self._on_power)
        self.auto_chk.toggled.connect(self._on_auto)
        self.rainbow_chk.toggled.connect(self._on_rainbow)
        self.btn_save.clicked.connect(self._profile_save)
        self.btn_load.clicked.connect(self._profile_load)
        self.btn_delete.clicked.connect(self._profile_delete)
        self.profile_list.itemDoubleClicked.connect(lambda _i: self._profile_load())
        self.auto_restore_chk.toggled.connect(lambda on: self._toggle_autostart("restore", on))
        self.auto_tray_chk.toggled.connect(lambda on: self._toggle_autostart("tray", on))

    def _wire_worker(self):
        self.worker.op_done.connect(self._on_op_done)
        self.worker.device_status.connect(self._on_device_status)
        self.worker.config_updated.connect(self._on_config_updated)

    # -- config <-> widgets --
    def _load_from_cfg(self, cfg):
        self._suppress = True
        self._color = QColor("#" + cfg.get("color", "aa00ff"))
        self._percent = int(cfg.get("percent", 100))   # HID intensity %

        fw = self.kbd.level() if self.kbd.available else None
        if self.kbd.available and fw is None:
            fw = self.kbd.max
        if fw is not None:
            self._expected_fw = fw
        self._brightness_b = self._b_from(fw, self._percent)

        h, s, v, _ = self._color.getHsvF()
        h = max(h, 0.0)              # gray -> hue is -1; clamp
        self.wheel.set_hsv(h, s, v)
        self.value_slider.setValue(int(v * 100))
        self.hex_edit.setText(self._color.name())
        self._update_swatch()
        self.bright_slider.setValue(self._brightness_b)
        self.bright_lbl.setText(f"{self._brightness_b}%")
        self.power_btn.setChecked(self._brightness_b > 0)
        self.power_btn.setText("On" if self._brightness_b > 0 else "Off")
        self.auto_chk.setChecked(bool(cfg.get("autonomous", False)))
        self._reload_profiles(cfg)
        self._suppress = False

    def _reload_profiles(self, cfg):
        self.profile_list.clear()
        for name in sorted(cfg.get("profiles", {})):
            self.profile_list.addItem(QListWidgetItem(name))

    def _update_swatch(self):
        self.swatch.setStyleSheet(
            f"background:{self._color.name()}; border:1px solid #333; border-radius:6px;"
        )

    def _current_hex(self):
        return self._color.name().lstrip("#")

    # -- interaction handlers --
    def _on_wheel(self, h, s):
        if self._suppress:
            return
        v = self.value_slider.value() / 100.0
        self._color = QColor.fromHsvF(h, s, v)
        self._sync_color_widgets(update_wheel=False)
        self._queue_preview()

    def _on_value(self, val):
        if self._suppress:
            return
        h, s, _v, _a = self._color.getHsvF()
        self._color = QColor.fromHsvF(max(h, 0.0), s, val / 100.0)
        self.wheel.set_value(val / 100.0)
        self._sync_color_widgets(update_wheel=False)
        self._queue_preview()

    def _apply_hex(self, text, commit=False):
        text = text.strip()
        if not text.startswith("#"):
            text = "#" + text
        col = QColor(text)
        if not col.isValid():
            return
        self._color = col
        self._sync_color_widgets(update_wheel=True)
        if commit:
            self._commit_color()

    def _sync_color_widgets(self, update_wheel):
        self._suppress = True
        if update_wheel:
            h, s, v, _ = self._color.getHsvF()
            self.wheel.set_hsv(max(h, 0.0), s, v)
            self.value_slider.setValue(int(v * 100))
        self.hex_edit.setText(self._color.name())
        self._update_swatch()
        self._suppress = False

    def _queue_preview(self):
        self._interacting = True
        self._pending = (self._current_hex(), self._percent)
        if not self._preview.isActive():
            self._preview.start()

    def _emit_preview(self):
        if not self._pending:
            return
        hexc, pct = self._pending
        self.worker.submit("color", hexc, pct, False)
        self._pending = None

    def _commit_color(self):
        self._preview.stop()
        self._pending = None
        self._interacting = False
        self.worker.submit("color", self._current_hex(), self._percent, True)

    def _on_brightness(self, val):
        if self._suppress:
            return
        # val is the unified brightness B; decompose into firmware step + HID intensity.
        self._brightness_b = val
        fw, hid = self._levels_for(val)
        self._percent = hid
        self.bright_lbl.setText(f"{val}%")
        self.power_btn.setChecked(val > 0)
        self.power_btn.setText("On" if val > 0 else "Off")
        if fw is not None:
            self._set_firmware(fw)
        self._queue_preview()

    def set_brightness_external(self, b):
        """Set unified brightness from the tray (or anywhere) and persist it."""
        b = max(0, min(100, int(b)))
        if self.bright_slider.value() == b:
            # value unchanged -> valueChanged won't fire; apply directly
            self._on_brightness(b)
        else:
            self.bright_slider.setValue(b)   # fires _on_brightness
        self._commit_color()

    def _on_power(self, checked):
        if self._suppress:
            return
        self.power_btn.setText("On" if checked else "Off")
        self.worker.submit("power", bool(checked))

    def _on_auto(self, checked):
        if self._suppress:
            return
        self.worker.submit("auto", bool(checked))

    def _on_rainbow(self, checked):
        if self._suppress:
            return
        self.worker.submit("rainbow", bool(checked))

    # -- autostart --
    def _load_autostart_state(self):
        self._suppress = True
        self.auto_restore_chk.setChecked(Autostart.is_enabled("restore"))
        self.auto_tray_chk.setChecked(Autostart.is_enabled("tray"))
        self._suppress = False

    def _toggle_autostart(self, key, on):
        if self._suppress:
            return
        try:
            Autostart.set_enabled(key, on)
            ok = True
        except OSError as exc:
            ok = False
            err = str(exc)
        label = "login restore" if key == "restore" else "tray autostart"
        self.status_lbl.setStyleSheet("color:#5c5;" if ok else "color:#d55;")
        self.status_lbl.setText(
            (f"{'Enabled' if on else 'Disabled'} {label}") if ok
            else f"✗ autostart: {err}"
        )

    # -- firmware (FN+F4/F3) polling --
    def _poll_firmware(self):
        if not self.kbd.available or self._interacting:
            return
        if time.monotonic() < self._fw_ignore_until:
            return
        cur = self.kbd.level()
        if cur is None or cur == self._expected_fw:
            return
        # FN key changed the firmware level -> mirror it into the slider + HID.
        self._expected_fw = cur
        b = int(round(cur * 100 / self.kbd.max))
        self._suppress = True
        self._brightness_b = b
        self._percent = 100              # FN snaps the HID sub-step to full
        self.bright_slider.setValue(b)
        self.bright_lbl.setText(f"{b}%")
        self.power_btn.setChecked(b > 0)
        self.power_btn.setText("On" if b > 0 else "Off")
        self._suppress = False
        # Persist the matching color/intensity (keeps the current color).
        self.worker.submit("color", self._current_hex(), self._percent, True)

    # -- profiles --
    def _profile_save(self):
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:")
        if ok and name.strip():
            self._commit_color()         # persist on-screen state first
            self.worker.submit("profile_save", name.strip())

    def _profile_load(self):
        item = self.profile_list.currentItem()
        if item:
            self.worker.submit("profile_load", item.text())

    def _profile_delete(self):
        item = self.profile_list.currentItem()
        if not item:
            return
        if QMessageBox.question(self, "Delete profile", f"Delete '{item.text()}'?") \
                == QMessageBox.StandardButton.Yes:
            self.worker.submit("profile_delete", item.text())

    # -- worker callbacks --
    def _on_op_done(self, op, ok, msg):
        self.status_lbl.setStyleSheet("color:#5c5;" if ok else "color:#d55;")
        self.status_lbl.setText(("✓ " if ok else "✗ ") + msg)

    def _on_device_status(self, devinfo, err):
        self._devinfo = devinfo
        present = devinfo is not None
        for w in self._dev_widgets:
            w.setEnabled(present)
        if present:
            rainbow_ok = bool(devinfo.get("rainbow_supported", False))
            self.rainbow_chk.setEnabled(rainbow_ok)
            if not rainbow_ok:
                self.rainbow_chk.setToolTip(
                    "OEM rainbow is not supported on this device mapping "
                    f"({devinfo.get('hid_id', '')})"
                )
            self.status_lbl.setStyleSheet("color:#5c5;")
            self.status_lbl.setText(
                f"● {devinfo.get('model', 'keyboard')}  ·  {devinfo.get('path', '')}"
            )
        else:
            self.rainbow_chk.setEnabled(False)
            self.status_lbl.setStyleSheet("color:#d55;")
            self.status_lbl.setText("✗ " + (err or "Keyboard not found"))

    def _on_config_updated(self, cfg):
        if self._interacting:
            self._reload_profiles(cfg)
            return
        self._load_from_cfg(cfg)


# ----------------------------------------------------------------------------
# Tray
# ----------------------------------------------------------------------------

class Tray(QSystemTrayIcon):
    def __init__(self, window: MainWindow, worker: DeviceWorker, app: QApplication):
        super().__init__(make_logo_icon())
        self.window = window
        self.worker = worker
        self.app = app
        self._tray_suppress = False
        self.setToolTip("VRGB — keyboard RGB")

        menu = QMenu()
        self.act_show = QAction("Show / hide window", self)
        self.act_show.triggered.connect(self._toggle_window)
        menu.addAction(self.act_show)
        menu.addSeparator()

        self.act_on = QAction("Turn on", self)
        self.act_on.triggered.connect(lambda: self.worker.submit("power", True))
        self.act_off = QAction("Turn off", self)
        self.act_off.triggered.connect(lambda: self.worker.submit("power", False))
        menu.addAction(self.act_on)
        menu.addAction(self.act_off)

        # Brightness as a submenu of discrete steps. KDE's tray menu is rendered over
        # DBusMenu, which cannot host an embedded QSlider widget — only plain items.
        self.bright_menu = menu.addMenu("Brightness")
        self._bright_group = QActionGroup(self)
        self._bright_group.setExclusive(True)
        self._bright_actions = []
        for pct in (10, 25, 50, 75, 100):
            a = QAction(f"{pct}%", self)
            a.setCheckable(True)
            a.triggered.connect(lambda _=False, p=pct: self.window.set_brightness_external(p))
            self._bright_group.addAction(a)
            self.bright_menu.addAction(a)
            self._bright_actions.append((pct, a))

        # Color as a submenu of preset swatches (colored icons) + the full dialog.
        self.color_menu = menu.addMenu("Color")
        for name, hexc in PRESETS:
            a = QAction(swatch_icon(hexc), name, self)
            a.triggered.connect(lambda _=False, h=hexc: self.window._apply_hex("#" + h, commit=True))
            self.color_menu.addAction(a)
        self.color_menu.addSeparator()
        self.act_more = QAction("More colors…", self)
        self.act_more.triggered.connect(self._pick_color)
        self.color_menu.addAction(self.act_more)

        menu.addSeparator()
        self.profiles_menu = menu.addMenu("Profiles")
        self._rebuild_profiles(window.mod.load_config())
        worker.config_updated.connect(self._rebuild_profiles)

        menu.addSeparator()
        self.act_quit = QAction("Quit", self)
        self.act_quit.triggered.connect(self._quit)
        menu.addAction(self.act_quit)

        menu.aboutToShow.connect(self._sync_controls)
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _sync_controls(self):
        # Tick the brightness step nearest the current unified brightness.
        b = self.window._brightness_b
        nearest = min(self._bright_actions, key=lambda pa: abs(pa[0] - b))[1]
        for _pct, a in self._bright_actions:
            a.setChecked(a is nearest)

    def _pick_color(self):
        col = QColorDialog.getColor(self.window._color, self.window, "Pick keyboard color")
        if col.isValid():
            self.window._apply_hex(col.name(), commit=True)

    def _rebuild_profiles(self, cfg):
        self.profiles_menu.clear()
        names = sorted(cfg.get("profiles", {}))
        if not names:
            a = QAction("(none saved)", self)
            a.setEnabled(False)
            self.profiles_menu.addAction(a)
            return
        for name in names:
            a = QAction(name, self)
            a.triggered.connect(lambda _=False, n=name: self.worker.submit("profile_load", n))
            self.profiles_menu.addAction(a)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_window()

    def _toggle_window(self):
        if self.window.isVisible() and not self.window.isMinimized():
            self.window.hide()
        else:
            self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()

    def _quit(self):
        self.worker.stop()
        if not self.worker.wait(3000):
            self.worker.terminate()
            self.worker.wait(1000)
        self.app.quit()


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("VRGB GUI")
    app.setWindowIcon(make_logo_icon())

    try:
        mod, _core_path = load_core()
    except FileNotFoundError as exc:
        QMessageBox.critical(None, "VRGB GUI", str(exc))
        return 1

    worker = DeviceWorker(mod)
    worker.start()

    window = MainWindow(worker, mod)

    tray = Tray(window, worker, app) if QSystemTrayIcon.isSystemTrayAvailable() else None
    if tray:
        app.setQuitOnLastWindowClosed(False)
        tray.show()

        def close_event(e):
            e.ignore()
            window.hide()
            tray.showMessage("VRGB", "Still running in the tray.",
                             QSystemTrayIcon.MessageIcon.Information, 2000)
        window.closeEvent = close_event

    if "--tray" in sys.argv and tray:
        pass  # start hidden to the tray
    else:
        window.show()

    rc = app.exec()
    worker.stop()
    if not worker.wait(3000):
        worker.terminate()
        worker.wait(1000)
    return rc


if __name__ == "__main__":
    sys.exit(main())
