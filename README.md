# QIDI Max4 – Fluidd box panel fix (firmware 01.01.07.01)

Unofficial fix for the **Material Control** (box / multi-colour) panel in Fluidd after the
**QD_MAX4 01.01.07.01** firmware update. Not affiliated with QIDI.

> **Applies to:** QIDI Max4 · firmware **QD_MAX4 01.01.07.01** · bundled **Fluidd v1.30.5** (`assets/index-DlFvHGAh.js`).
> Different model or version? Run the [read-only check](#other-qidi-printers-or-something-does-not-work) first.
> After a QIDI update, [run the script again](#after-the-next-qidi-update); to undo, see [Undo](#undo).
> What changed between versions: [CHANGELOG](CHANGELOG.md).

| Before: stock Fluidd after the update | After: with this fix |
|---|---|
| ![Fluidd box panel before the fix: every slot shows a question mark](docs/before.png) | ![Fluidd box panel after the fix: slots show material and colour](docs/after.png) |

## The problem

After updating to 01.01.07.01 the box works on the printer screen and in QIDI Studio, but in Fluidd:

- every box slot shows **`?`** instead of the material and colour,
- **Load / Unload / Eject** and the RFID read do nothing (Fluidd sends commands the new firmware no longer has),
- changing vendor / material / colour in Fluidd writes data in the old format.

**Cause:** the update changed how slot materials are stored and renamed the box G-code commands,
but the Fluidd build shipped with it (v1.30.5) was never updated to match.

| | Before the update (what Fluidd expects) | After the update |
|---|---|---|
| `filament_slotN` | `7` (index in `officiall_filas_list.cfg`) | `"QFG00"` (filament ID) |
| `color_slotN` | `3` (index in a colour list) | `["060606"]` (hex list) |
| Eject | `E_BOX slot=N` | `EJECT_FILAMENT_CONTROL SLOT=N` |
| Load | `E_LOAD slot=N` | `LOAD_FILAMENT_CONTROL SLOT=N` |
| Unload | `E_UNLOAD slot=N` | `UNLOAD_FILAMENT_CONTROL SLOT=N` |
| RFID read | `RFID_READ SLOT=slotN` | `READ_RFID SLOT=N` |
| Change material | `SAVE_VARIABLE …` | `UPDATE_FILAMENT_INFORMATION SLOT=N COLOR='RRGGBB' VENDOR='QIDI' FILAMENT='PETG Basic'` |

One more problem: the new `multi_color_controller` object reports only *changed* fields in its status updates,
at any depth (for example `extra.filament_info` with just the new colour). Fluidd replaces nested objects on every
update, so after a few seconds it loses the "box filament is in the path" flag (`b_endstop_state`). That is why
**Unload** stays greyed out even with a slot loaded.

## What the fix does

The script patches two Fluidd files on the printer (`assets/index-*.js` and `sw.js`):

- slot material, vendor and colour come from `box_extras`, and the external spool (Rack) from
  `multi_color_controller.extra` (the same data QIDI Studio shows),
- Eject / Load / Unload / RFID send the new commands,
- changing vendor, material or colour (box slots and the Rack) sends `UPDATE_FILAMENT_INFORMATION`, the same command
  QIDI Studio sends, and the firmware sets the print temperatures itself.
  The vendor and material lists come from QIDI's filament database for the **installed nozzle size**,
  so you can only pick what the firmware knows,
- `multi_color_controller` updates are merged, so Unload is enabled when a slot is loaded,
- the print-start dialog matches the file's materials to box slots using the new data, so it no longer shows `?`
  and blocks **Print**,
- the pre-print check with the box disabled reads the external filament sensor and `multi_color_controller`,
  because `box_extras` no longer has those fields,
- `sw.js` gets a new revision so browsers load the patched file instead of a cached one.

Nothing in Klipper, Moonraker or the printer config is changed.

## Compatibility

- QIDI Max4, firmware **QD_MAX4 01.01.07.01** (release 2026-10-16) with the Fluidd v1.30.5 shipped in it.
- The script checks every place it changes. On any other Fluidd build it stops **without changing anything**.
- Tested on one printer with one QIDI Box (box firmware 02.03.01.21), the Rack, and spools without RFID tags.
  With the box disabled and no filament in the toolhead, the pre-print check correctly reports "No filament detected".
  **Not tested:** several boxes, the RS485 box, RFID-tagged spools, the box-disabled check with filament loaded.
  Feedback is welcome in the Issues.
- **QIDI Q2:** reported (#2) to ship the same Fluidd build, so the script should fit it. Not tested here; run `--check`.
- **QIDI Plus 4 (firmware 2.1.1):** reported (#1) to still use the old slot format, so this fix does not apply there.

## Install

You need SSH access to the printer. The factory default login on the Max4 is user `qidi`, password `qiditech`
(if you changed it, use your own).

**1. Copy the script to the printer.** Choose one:

- **a)** In Fluidd go to **Configuration**, upload `qidi_fluidd_box_fix.py`. It lands in `~/printer_data/config/`.
- **b)** Download it directly over SSH:
  ```bash
  curl -fsSL -o ~/qidi_fluidd_box_fix.py https://raw.githubusercontent.com/Assur92/qidi-max4-fluidd-box-fix/main/qidi_fluidd_box_fix.py
  ```

Optional: check that you got the right file. `sha256sum ~/qidi_fluidd_box_fix.py` should print
`231f2a9710746fc5c3573af178f4968d4ba3557830dbf0df43c6cb40cc2b888d` (version `qd-box-fix-v3`).

**2. Run it over SSH** (use the path where you put the script):

```bash
sudo python3 ~/printer_data/config/qidi_fluidd_box_fix.py
```

You can check first without changing anything:

```bash
python3 ~/printer_data/config/qidi_fluidd_box_fix.py --dry-run
```

If `python3` is not found, use Klipper's Python instead: `sudo ~/klippy-env/bin/python …` with the same arguments.

The script saves the original files as `*.orig` next to them. If you used option a), you can delete the script
from Configuration afterwards.

**3. Reload Fluidd.** Close **every** Fluidd tab, open Fluidd again and press **Ctrl+F5**.
On a phone, close the tab and open the page again. A plain refresh is not enough, because Fluidd's service worker keeps
the old version while any Fluidd tab is open.

## Other QIDI printers, or something does not work

The fix was made and tested only on the Max4. Other QIDI models with a box may have the same problem,
but they are **untested**. Before patching anything, run the read-only check:

```bash
python3 ~/qidi_fluidd_box_fix.py --check
```

It changes nothing. It reads the Fluidd files and asks the printer's Moonraker whether the box commands and data
the fix relies on are there, then prints a short report ending with **looks compatible** or **NOT compatible as is**.
The report has no IP addresses, hostnames or serial numbers.

Please [open an issue](https://github.com/Assur92/qidi-max4-fluidd-box-fix/issues) and paste the whole report,
with your printer model. That is how support for other models can be added safely.
If your Fluidd lives somewhere else than `/home/qidi/fluidd`, add `--fluidd-dir /path/to/fluidd`.

## Undo

```bash
sudo python3 ~/printer_data/config/qidi_fluidd_box_fix.py --restore
```

Then close the Fluidd tabs, reopen and press Ctrl+F5 again.

## After the next QIDI update

A firmware update will probably replace Fluidd and remove the fix. Run the script again.
If QIDI changed Fluidd, the script stops without changing anything. Then either QIDI fixed it,
or the script needs an update (open an Issue).

## Limitations

- The material lists are built into the script from the 01.01.07.01 update (0.2 / 0.4 / 0.6 / 0.8 mm nozzles).
  If QIDI adds materials in a later update, they will be missing until the script is updated.
- QIDI's own macros `M603` / `M604` in `klipper-macros-qd/filament.cfg` still call `E_LOAD` / `E_UNLOAD`, which the
  new firmware no longer registers. That is a bug in the QIDI update itself; this script does not touch it.

## Credits

Thanks to [ThorSc](https://github.com/ThorSc/qidi-max4-plus4-fluidd-box-patch) (Max 4 / Plus 4) and
[Greg-LFT](https://github.com/Greg-LFT/Qidi-Q2-Fluidd-widget-box-repair) (Q2) for cross-checking and ideas:
per-nozzle material lists, the Rack via `multi_color_controller.extra`, and the pre-print check fallback.

## Disclaimer

Unofficial. You change files on your own printer at your own risk. QIDI may treat modified system files as
unsupported. The script backs up the original files and can restore them.

## License

GPL-3.0, the same as [Fluidd](https://github.com/fluidd-core/fluidd), which this patches.
