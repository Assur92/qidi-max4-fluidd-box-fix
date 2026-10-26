#!/usr/bin/env python3
"""Unofficial fix for the Fluidd "Material Control" (box) panel on the QIDI Max4
after the QD_MAX4 01.01.07.01 firmware update.

The new firmware stores slot materials in a new format (filament ID "QFG00",
colour ["060606"]) and replaced the box G-code commands, but the Fluidd build
shipped with it (v1.30.5) was not updated. Result: "?" instead of materials,
dead Load/Unload/Eject buttons and broken material editing.

This script patches the Fluidd files in place:
  * slot material, vendor and colour are read from box_extras.boxes[].filament_info
    (the same data QIDI Studio shows),
  * Eject/Load/Unload and RFID read send EJECT_/LOAD_/UNLOAD_FILAMENT_CONTROL and
    READ_RFID instead of the removed E_BOX/E_LOAD/E_UNLOAD/RFID_READ,
  * changing vendor/material/colour sends UPDATE_FILAMENT_INFORMATION (the command
    QIDI Studio uses); the lists come from QIDI's new filament database,
  * multi_color_controller updates are merged instead of replaced, so the
    "box filament in path" state (b_endstop_state) is not lost,
  * sw.js gets a new revision so browsers fetch the patched file.

Usage (on the printer):
  sudo python3 qidi_fluidd_box_fix.py             apply (backs up originals to *.orig)
  sudo python3 qidi_fluidd_box_fix.py --restore   put the original files back
  python3 qidi_fluidd_box_fix.py --dry-run        only check whether the patch fits
Options: --fluidd-dir DIR (default /home/qidi/fluidd)
"""
import argparse
import json
import pathlib
import re
import shutil
import sys

VERSION = "qd-box-fix-v1"
MARKER = "qd-box-fix-"
DEFAULT_DIR = "/home/qidi/fluidd"

# Vendors and materials from QIDI_Client/resource/filament_config/filament-0.4.json
# (the 0.4 file contains every entry of the other nozzle files). The firmware looks up "<vendor> <material>".
FILAMENT_DB = {
    "QIDI": ["PLA Basic", "PLA Matte Basic", "PLA Rapido", "PLA Rapido Matte", "PLA Rapido Metal", "PLA Silk",
             "WOOD Rapido", "PLA-CF", "ASA", "ASA-Aero", "ABS-GF", "ASA-CF20 Core", "ABS Odorless", "ABS Rapido",
             "ABS Rapido Metal", "PC/ABS-FR", "PETG Basic", "PETG Rapido", "PETG Tough", "PETG Translucent",
             "PETG-CF", "PETG-GF", "PAHT-CF", "PA6-CF", "PA12-CF", "PAHT-GF", "UltraPA", "UltraPA-CF25", "PPS-CF",
             "PPS-GF", "Support For PET/PA", "Support For PAHT", "PET-CF", "PET-GF", "TPU-Aero", "TPU 95A-HF",
             "TPU-GF", "PEBA 95A"],
    "Generic": ["ABS", "PC", "PETG", "PLA", "PLA Silk", "PLA+", "TPU 95A"],
    "Bambu": ["ABS", "PETG", "PLA"],
    "HATCHBOX": ["ABS", "PETG", "PLA"],
    "Overture": ["ABS", "PLA"],
    "Polymaker": ["ABS", "PLA", "PLA-HT"],
}

# Slot data from box_extras, injected into the `items` loop where m is the slot (0..15)
# and C/w/S are colour, material and vendor.
SLOT_FROM_BOX_EXTRAS = (
    "/*" + VERSION + "*/{const fi=this.$store.state.printer.printer.box_extras?.boxes?.[Math.floor(m/4)]"
    "?.filament_info?.[m%4];if(fi){const fc=fi.color_rgb_str?.[0];"
    "fc&&(C=\"#\"+String(fc).replace(\"#\",\"\"));w=fi.filament_str||w;S=fi.vendor_str||S}}"
)

# Methods added to the panel component. qdUpdateSlot fills the fields that were not
# changed from the current slot state and sends the command in QIDI Studio's format.
SLOT_METHODS = (
    "qdNewFw(){return this.selectIndex<16&&!!this.$store.state.printer.printer.box_extras?.boxes?.[0]?.filament_info}"
    "qdDb(){return " + json.dumps(FILAMENT_DB, separators=(",", ":")) + "}"
    "qdUpdateSlot(o){const db=this.qdDb(),it=this.items[this.selectIndex]||{};"
    "let v=o.vendor??it.vendor,f=o.filament??it.filament;"
    "db[v]||(v=Object.keys(db).find(k=>db[k].includes(f))??\"QIDI\");"
    "db[v].includes(f)||(f=db[v].find(n=>n===String(f).split(/[ -]/)[0])??db[v][0]);"
    "let c=String(o.color??it.color??\"\").replace(\"#\",\"\").toUpperCase();"
    "/^[0-9A-F]{6}$/.test(c)||(c=\"FAFAFA\");"
    "I.printerGcodeScript(`UPDATE_FILAMENT_INFORMATION SLOT=${this.selectIndex} COLOR='${c}' VENDOR='${v}' FILAMENT='${f}'`)}"
)

RACK_GUARD = (
    "if(this.selectIndex===16&&Array.isArray(this.variables.rackExtra[0])){alert(\"The new QIDI firmware stores "
    "materials in a different format. Change the external spool material in QIDI Studio or on the printer screen.\");return}"
)


def edit_guard(field):
    return "if(this.qdNewFw()){this.qdUpdateSlot({" + field + ":t});return}" + RACK_GUARD


# (original, replacement[, expected count])
BUNDLE_REPLACEMENTS = [
    (
        'vendor_list[this.variables.vendorSlot[m]])??"",this.itemsCopy.push(',
        'vendor_list[this.variables.vendorSlot[m]])??"";' + SLOT_FROM_BOX_EXTRAS + "this.itemsCopy.push(",
    ),
    (
        'color:((u=this.officialFilasListDictData)==null?void 0:u.colordict[this.variables.rackExtra[0]])??"#00000000"',
        'color:(Array.isArray(this.variables.rackExtra[0])?"#"+String(this.variables.rackExtra[0][0]).replace("#",""):void 0)'
        '??((u=this.officialFilasListDictData)==null?void 0:u.colordict[this.variables.rackExtra[0]])??"#00000000"',
    ),
    ("set selectedVendor(t){", "set selectedVendor(t){" + edit_guard("vendor")),
    ("set selectedFilament(t){", "set selectedFilament(t){" + edit_guard("filament")),
    ("set selectedColor(t){", "set selectedColor(t){" + edit_guard("color")),
    ("get vendorItems(){", "get vendorItems(){if(this.qdNewFw())return Object.keys(this.qdDb());"),
    (
        "get filamentItems(){",
        "get filamentItems(){if(this.qdNewFw()){const d=this.qdDb();return d[this.items[this.selectIndex]?.vendor]??d.QIDI}",
    ),
    (
        "created(){this.$store.state.printer.officiallFilasList?",
        SLOT_METHODS + "created(){this.$store.state.printer.officiallFilasList?",
    ),
    (
        'const n=["E_BOX","E_LOAD","E_UNLOAD"];I.printerGcodeScript(`${n[t-1]} slot=${s}`)',
        'const n=["EJECT_FILAMENT_CONTROL","LOAD_FILAMENT_CONTROL","UNLOAD_FILAMENT_CONTROL"];'
        "I.printerGcodeScript(`${n[t-1]} SLOT=${s}`)",
    ),
    ("RFID_READ SLOT=slot${t}", "READ_RFID SLOT=${t}"),
    (
        "this.$store.state.printer.printer.box_extras.b_endstop_state===0&&this.variables.lastLoadSlot",
        "(this.$store.state.printer.printer.box_extras.b_endstop_state"
        "??this.$store.state.printer.printer.multi_color_controller?.box?.b_endstop_state)===0"
        "&&this.variables.lastLoadSlot",
        2,
    ),
    (
        "t[s]!==e.payload[s]&&$.set(r.printer[e.key],s,e.payload[s])",
        "t[s]!==e.payload[s]&&$.set(r.printer[e.key],s,e.key===\"multi_color_controller\"&&t[s]"
        "&&typeof t[s]==\"object\"&&!Array.isArray(t[s])&&e.payload[s]&&typeof e.payload[s]==\"object\""
        "&&!Array.isArray(e.payload[s])?{...t[s],...e.payload[s]}:e.payload[s])",
    ),
]


def sw_replacements(bundle):
    return [('{"revision":null,"url":"' + bundle + '"}', '{"revision":"' + VERSION + '","url":"' + bundle + '"}')]


def fail(msg):
    sys.exit("ERROR: " + msg)


# open() with newline="" keeps line endings byte for byte; pathlib's write_text(newline=) needs Python 3.10,
# while the printer runs 3.9.
def read_file(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write_file(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def find_bundle(root):
    index = root / "index.html"
    if not index.is_file():
        fail(f"{index} not found - is {root} the Fluidd directory?")
    names = re.findall(r'src="(?:\./|/)?(assets/index-[\w-]+\.js)"', read_file(index))
    if len(names) != 1:
        fail(f"could not find the main script in {index}")
    return names[0]


def backup_path(path):
    return path.with_name(path.name + ".orig")


def original_text(path):
    """Text of the unpatched file: the file itself, or its backup if the file was patched before."""
    text = read_file(path)
    if MARKER not in text:
        return text
    backup = backup_path(path)
    if not backup.is_file():
        fail(f"{path} is already patched but {backup} is missing - reinstall Fluidd from the QIDI update first")
    text = read_file(backup)
    if MARKER in text:
        fail(f"{backup} is a patched file, not the original")
    return text


def apply_replacements(path, text, replacements):
    for old, new, *expected in replacements:
        expected = expected[0] if expected else 1
        count = text.count(old)
        if count != expected:
            fail(
                f"{path.name}: expected {expected} match(es), found {count}. This Fluidd build is not the one the "
                f"patch was made for (QD_MAX4 01.01.07.01, Fluidd v1.30.5). Nothing was changed.\n  {old[:100]}"
            )
        text = text.replace(old, new)
    return text


def patch(root, dry_run):
    bundle = find_bundle(root)
    files = [(root / bundle, BUNDLE_REPLACEMENTS), (root / "sw.js", sw_replacements(bundle))]

    current = {path: read_file(path) for path, _ in files}
    if all(VERSION in text for text in current.values()):
        print(f"Already patched with {VERSION}, nothing to do.")
        return

    # Build every patched file before writing anything, so a mismatch leaves the files untouched.
    patched = {path: apply_replacements(path, original_text(path), repl) for path, repl in files}
    if dry_run:
        print("Dry run OK: the patch fits this Fluidd build. Nothing was changed.")
        return

    for path, text in patched.items():
        # An unpatched file is the current original (maybe from a newer QIDI update), so it always
        # becomes the backup; a patched file keeps the backup made when it was first patched.
        if MARKER not in current[path]:
            backup = backup_path(path)
            shutil.copy2(path, backup)
            print(f"Backup:  {backup}")
        write_file(path, text)
        print(f"Patched: {path}")
    print("\nDone. Close every Fluidd tab, open Fluidd again and press Ctrl+F5 (on a phone: close the tab and reopen).")


def restore(root):
    bundle = find_bundle(root)
    restored = 0
    for path in (root / bundle, root / "sw.js"):
        backup = backup_path(path)
        if MARKER not in read_file(path):
            print(f"{path} is not patched, skipped")
            continue
        if not backup.is_file():
            print(f"No backup for {path}, skipped")
            continue
        if MARKER in read_file(backup):
            fail(f"{backup} is a patched file, not the original")
        shutil.copyfile(backup, path)
        backup.unlink()
        restored += 1
        print(f"Restored: {path}")
    if restored:
        print("\nDone. Close every Fluidd tab, open Fluidd again and press Ctrl+F5.")


def main():
    parser = argparse.ArgumentParser(description="Fix the Fluidd box panel for QIDI Max4 firmware 01.01.07.01")
    parser.add_argument("--fluidd-dir", default=DEFAULT_DIR, help=f"Fluidd directory (default {DEFAULT_DIR})")
    parser.add_argument("--restore", action="store_true", help="restore the original Fluidd files")
    parser.add_argument("--dry-run", action="store_true", help="only check whether the patch fits")
    args = parser.parse_args()

    root = pathlib.Path(args.fluidd_dir)
    try:
        if args.restore:
            restore(root)
        else:
            patch(root, args.dry_run)
    except PermissionError as e:
        fail(f"{e}\nRun the script with sudo.")


if __name__ == "__main__":
    main()
