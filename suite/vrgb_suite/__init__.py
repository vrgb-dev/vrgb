"""VRGB Suite — PyQt6 GUI, tray and automation on top of VRGB Core.

Core (`vrgb`, the single-file CLI/module) stays dependency-free; everything with a
GUI, desktop integration or extra logic lives in this package:

  core.py     locate/import VRGB Core; safe pkexec target
  worker.py   device I/O thread (calls Core's cmd_* / set_color)
  app.py      main window, tray, single instance, entry point
  idle.py     idle detection backends (GNOME, Wayland, X11)
  sun.py      sunrise/sunset, location suggestion, Suite settings
  system.py   firmware backlight (logind) and XDG autostart
  widgets.py  color wheel and icons

Design:
  * The Suite imports VRGB Core (`import vrgb`, or the CLI file by path for
    ./install.sh installs) and calls it in-process for low-latency control of the
    keyboard. HID protocol, report-id mapping and config logic stay in Core.
  * All device I/O happens on a dedicated worker thread so the UI never blocks.
  * If opening the hidraw device raises PermissionError (e.g. the user is in the `vrgb`
    group but has not logged out/in yet, so the group is not active in this session),
    persisting actions fall back to `pkexec vrgb ...`, which prompts for a password via
    Polkit and runs as root. Live "preview" drags are best-effort and silently skipped
    in that case (to avoid password spam) until the group is active.

    The pkexec fallback ONLY ever runs a root-owned system copy of the CLI
    (/usr/bin/vrgb from a package, or /usr/local/bin/vrgb from ./install.sh); it
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

Automation (runs inside this process, so the tray must be running):
  * Idle dimming — GNOME Mutter IdleMonitor, Wayland ext-idle-notify-v1 (KDE,
    wlroots compositors…) or X11 XScreenSaver, see idle.make_idle_backend().
    Dimming/restoring only touches the HID intensity and never the saved config, so
    the sliders keep showing the user's real brightness. Paused while the rainbow
    is the saved mode, whose process would overwrite a dimmed frame.
  * Daytime off — while the sun is up at the configured location (computed locally,
    see sun.sun_times) the backlight is switched off; it comes back at sunset if it
    was on before. The location is suggested from the system timezone.

  * Session start (`vrgb-gui --tray`) — restores the lighting (resuming a saved
    rainbow), or keeps it off by day.

Rainbow: the Suite does not run the cycle loop itself. It starts Core's
`vrgb cycle` as a separate process (worker._start_cycle), which hands the cycle to
vrgb-restore.service when enabled or keeps running on its own, so the rainbow
outlives the GUI. Brightness changes go through cmd_brightness, which the running
cycle picks up from the config; a new color goes through cmd_set, which stops it.

State lives in ~/.config/vrgb/config.json: Core's keys (color / intensity / profiles /
autonomous) plus the Suite's own (see sun.DEFAULTS); Core preserves unknown keys.
"""

__version__ = "1.1.0"  # released together with Core (vrgb.VERSION)
