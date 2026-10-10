# Contributing to VRGB

Thanks for helping. Bug fixes, hardware reports, and new device mappings are all welcome.

## Ground rules

- **Core (`vrgb.py`) stays a single file using only the Python standard library**, and must keep working on Python 3.8. Anything that needs a GUI, desktop integration, or a third-party dependency belongs in the Suite (`suite/vrgb_suite/`).
- The Suite builds on Core and never changes how Core behaves. HID protocol, report IDs, and config logic live only in Core.

## Development

Run from a checkout without installing:

```sh
python3 vrgb.py --debug status
PYTHONPATH=.:suite python3 -m vrgb_suite
```

Run the tests (no keyboard needed, HID writes are captured):

```sh
pip install pytest
pytest                                   # all tests
pytest tests/test_core.py -k find_device # a subset
```

CI runs the tests on Python 3.8 to 3.13, checks that Core and Suite versions match, and runs `shellcheck -S warning` on the install scripts.

## Commit messages and releases

CI runs automatically on pushes and pull requests to validate tests, Python compilation,
version consistency, and the install scripts. CI does **not** create tags or GitHub releases.

Releases are intentionally manual and happen only after the merged tree has been tested on
real supported hardware. The maintainer creates the release/tag from GitHub after that
validation. `scripts/build-release.sh` is retained as a local/manual helper for building
release assets; it is not invoked automatically by CI.

Conventional Commit messages are welcome because they keep history readable, but they do
not trigger a release.

### AUR packages

The AUR package base `vrgb` (packages `vrgb` and `vrgb-gui`) is kept in `packaging/aur/`.
Publishing a GitHub release runs `.github/workflows/aur.yml`, which sets the new version
and checksum (`packaging/aur/update-aur.sh`), test-builds both packages in an Arch
container and pushes to the AUR. Draft and pre-releases are not published.

For a packaging-only fix (e.g. a changed dependency), edit `packaging/aur/PKGBUILD`, then
run the workflow by hand from the Actions tab with the same version and `pkgrel` 2, 3, …;
leave "dry run" checked first to see the build without pushing. To try it locally on Arch:
`packaging/aur/update-aur.sh 1.0.0 1 /tmp/aur --build`.

The workflow needs the repository secret `AUR_SSH_PRIVATE_KEY` (a dedicated key registered
on an AUR account that maintains or co-maintains `vrgb`). Without it the workflow still
test-builds and then skips the push with a warning; the AUR maintainer publishes by hand.

## Adding a new device

VRGB already drives any HID LampArray keyboard it finds, reading the report IDs from the device's report descriptor; `vrgb status` shows such a device as unverified. A verified mapping adds what the descriptor cannot tell: the confirmed models and required kernel modules. It needs a report from someone who has tested it on a real laptop.

1. Collect the device identifiers:

   ```sh
   grep -H . /sys/class/hidraw/*/device/uevent | grep -E 'HID_ID|HID_NAME'
   vrgb --debug status
   ```

2. Add an entry to `SUPPORTED_DEVICES` in `vrgb.py` with the firmware and color report IDs printed by `vrgb --debug status`, the confirmed models, and any required kernel modules.
3. Add the device's exact report bytes to `test_verified_device_bytes` in `tests/test_core.py`. The table-driven tests cover the new entry automatically. If you can, also add its descriptor (`/sys/class/hidraw/hidrawN/device/report_descriptor`) to `tests/data/` with a parser test.
4. List it under "Verified mappings" in `README.md`.

## Reporting hardware results

Open an issue with your laptop model, the `HID_ID` and `HID_NAME` lines above, the output of `vrgb --debug status`, and which commands worked (static color, brightness, `auto`, `rainbow`, and `cycle`).
