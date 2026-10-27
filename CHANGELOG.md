# Changelog

The version is stored in the patched Fluidd files (`qd-box-fix-vN`). `--check` shows which one is installed.
Running a newer script on a patched printer upgrades it in place; the backups of the original files are kept.

## v3 – 2026-10-27

- **Print-start dialog:** the file's materials are matched to box slots using the new firmware data.
  Before, the dialog showed `?` instead of a slot and **Print** stayed disabled.

## v2 – 2026-10-27

- **Rack (external spool):** shown from `multi_color_controller.extra` (same as QIDI Studio) and editable
  from Fluidd (`UPDATE_FILAMENT_INFORMATION SLOT=16`).
- **Material lists follow the installed nozzle** (0.2 / 0.4 / 0.6 / 0.8 mm) instead of always using the 0.4 list.
- **Fix:** the Rack material disappeared after a colour change. The firmware sends partial updates inside nested
  objects too, so `multi_color_controller` updates are now merged at every level.
- **Pre-print check with the box disabled** reads the filament sensor, because the old fields are gone.
- README: corrected the "unknown command" claim, added Q2 / Plus 4 notes, SHA-256 of the script, credits.

Ideas from [ThorSc](https://github.com/Assur92/qidi-max4-fluidd-box-fix/issues/1) and
[Greg-LFT](https://github.com/Assur92/qidi-max4-fluidd-box-fix/issues/2).

## v1 – 2026-10-26

First release.

- Box slots show material, vendor and colour from the new firmware data instead of `?`.
- Eject / Load / Unload / RFID send the new commands (`EJECT_` / `LOAD_` / `UNLOAD_FILAMENT_CONTROL`, `READ_RFID`).
- Vendor / material / colour editing sends `UPDATE_FILAMENT_INFORMATION`, like QIDI Studio.
- Unload is enabled when a slot is loaded (`multi_color_controller` updates are merged).
- Automatic backup of the original files, `--restore`, `--dry-run`.

Fixes and additions on the same day:

- Fixed a crash on Python 3.9, the printer's Python. The script stopped before changing any Fluidd file.
- Added `--check`, a read-only compatibility report for GitHub issues.
- When the script refuses to patch, it now shows the Fluidd version it found next to the expected one.
- Added an issue form and before/after screenshots.
