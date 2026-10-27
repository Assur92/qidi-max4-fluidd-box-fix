#!/usr/bin/env python3
"""Unofficial fix for the Fluidd "Material Control" (box) panel on the QIDI Max4
after the QD_MAX4 01.01.07.01 firmware update.

The new firmware stores slot materials in a new format (filament ID "QFG00",
colour ["060606"]) and replaced the box G-code commands, but the Fluidd build
shipped with it (v1.30.5) was not updated. Result: "?" instead of materials,
dead Load/Unload/Eject buttons and broken material editing.

This script patches the Fluidd files in place:
  * slot material, vendor and colour are read from box_extras.boxes[].filament_info and
    the external spool from multi_color_controller.extra (the same data QIDI Studio shows),
  * Eject/Load/Unload and RFID read send EJECT_/LOAD_/UNLOAD_FILAMENT_CONTROL and
    READ_RFID instead of the removed E_BOX/E_LOAD/E_UNLOAD/RFID_READ,
  * changing vendor/material/colour sends UPDATE_FILAMENT_INFORMATION (the command
    QIDI Studio uses); the lists come from QIDI's filament database for the installed nozzle,
  * multi_color_controller updates are merged recursively instead of replaced, so the
    "box filament in path" state (b_endstop_state) and the Rack data are not lost,
  * the pre-print check with the box disabled falls back to the filament sensor,
  * sw.js gets a new revision so browsers fetch the patched file.

Usage (on the printer):
  sudo python3 qidi_fluidd_box_fix.py             apply (backs up originals to *.orig)
  sudo python3 qidi_fluidd_box_fix.py --restore   put the original files back
  python3 qidi_fluidd_box_fix.py --dry-run        only check whether the patch fits
  python3 qidi_fluidd_box_fix.py --check          read-only compatibility report to paste into a GitHub issue
Options: --fluidd-dir DIR (default /home/qidi/fluidd), --moonraker URL (default http://127.0.0.1:7125)
"""
import argparse
import hashlib
import json
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

VERSION = "qd-box-fix-v2"
MARKER = "qd-box-fix-"
DEFAULT_DIR = "/home/qidi/fluidd"
DEFAULT_MOONRAKER = "http://127.0.0.1:7125"
REPO = "https://github.com/Assur92/qidi-max4-fluidd-box-fix"
TARGET = "QD_MAX4 01.01.07.01 with Fluidd v1.30.5 (assets/index-DlFvHGAh.js)"

# Firmware features the patched Fluidd relies on; --check looks for them.
NEW_COMMANDS = ["LOAD_FILAMENT_CONTROL", "UNLOAD_FILAMENT_CONTROL", "EJECT_FILAMENT_CONTROL", "READ_RFID",
                "UPDATE_FILAMENT_INFORMATION"]
OLD_COMMANDS = ["E_LOAD", "E_UNLOAD", "E_BOX", "RFID_READ"]
FILAMENT_INFO_KEYS = ["vendor_str", "filament_str", "color_rgb_str"]

# Vendors and materials per nozzle size, from QIDI_Client/resource/filament_config/filament-<nozzle>.json
# in the 01.01.07.01 update. The firmware looks up "<vendor> <material>".
FILAMENT_DB = {
    "0.2": {
        "QIDI": ["PLA Basic", "PLA Matte Basic", "PLA Rapido", "PLA Rapido Matte", "PLA Rapido Metal", "ASA", "ABS Odorless", "ABS Rapido", "ABS Rapido Metal", "PETG Basic", "PETG Rapido", "PETG Tough", "PETG Translucent"],
        "Generic": ["ABS", "PC", "PETG", "PLA", "PLA+"],
        "Bambu": ["ABS", "PETG", "PLA"],
        "HATCHBOX": ["ABS", "PETG", "PLA"],
        "Overture": ["ABS", "PLA"],
        "Polymaker": ["ABS", "PLA", "PLA-HT"],
    },
    "0.4": {
        "QIDI": ["PLA Basic", "PLA Matte Basic", "PLA Rapido", "PLA Rapido Matte", "PLA Rapido Metal", "PLA Silk", "WOOD Rapido", "PLA-CF", "ASA", "ASA-Aero", "ABS-GF", "ASA-CF20 Core", "ABS Odorless", "ABS Rapido", "ABS Rapido Metal", "PC/ABS-FR", "PETG Basic", "PETG Rapido", "PETG Tough", "PETG Translucent", "PETG-CF", "PETG-GF", "PAHT-CF", "PA6-CF", "PA12-CF", "PAHT-GF", "UltraPA", "UltraPA-CF25", "PPS-CF", "PPS-GF", "Support For PET/PA", "Support For PAHT", "PET-CF", "PET-GF", "TPU-Aero", "TPU 95A-HF", "TPU-GF", "PEBA 95A"],
        "Generic": ["ABS", "PC", "PETG", "PLA", "PLA Silk", "PLA+", "TPU 95A"],
        "Bambu": ["ABS", "PETG", "PLA"],
        "HATCHBOX": ["ABS", "PETG", "PLA"],
        "Overture": ["ABS", "PLA"],
        "Polymaker": ["ABS", "PLA", "PLA-HT"],
    },
    "0.6": {
        "QIDI": ["PLA Basic", "PLA Matte Basic", "PLA Rapido", "PLA Rapido Matte", "PLA Rapido Metal", "PLA Silk", "WOOD Rapido", "PLA-CF", "ASA", "ABS-GF", "ASA-CF20 Core", "ABS Odorless", "ABS Rapido", "ABS Rapido Metal", "PC/ABS-FR", "PETG Basic", "PETG Rapido", "PETG Tough", "PETG Translucent", "PETG-CF", "PETG-GF", "PAHT-CF", "PA6-CF", "PA12-CF", "PAHT-GF", "UltraPA", "UltraPA-CF25", "PPS-CF", "PPS-GF", "Support For PET/PA", "Support For PAHT", "PET-CF", "PET-GF", "TPU-Aero", "TPU 95A-HF", "TPU-GF", "PEBA 95A"],
        "Generic": ["ABS", "PC", "PETG", "PLA", "PLA Silk", "PLA+", "TPU 95A"],
        "Bambu": ["ABS", "PETG", "PLA"],
        "HATCHBOX": ["ABS", "PETG", "PLA"],
        "Overture": ["ABS", "PLA"],
        "Polymaker": ["ABS", "PLA", "PLA-HT"],
    },
    "0.8": {
        "QIDI": ["PLA Basic", "PLA Matte Basic", "PLA Rapido", "PLA Rapido Matte", "PLA Rapido Metal", "WOOD Rapido", "PLA-CF", "ASA", "ABS-GF", "ASA-CF20 Core", "ABS Odorless", "ABS Rapido", "ABS Rapido Metal", "PC/ABS-FR", "PETG Basic", "PETG Rapido", "PETG Tough", "PETG Translucent", "PETG-CF", "PETG-GF", "PAHT-CF", "PA6-CF", "PA12-CF", "PAHT-GF", "UltraPA", "UltraPA-CF25", "PPS-CF", "PPS-GF", "Support For PET/PA", "Support For PAHT", "PET-CF", "PET-GF", "TPU 95A-HF", "TPU-GF"],
        "Generic": ["ABS", "PC", "PETG", "PLA", "PLA+", "TPU 95A"],
        "Bambu": ["ABS", "PETG", "PLA"],
        "HATCHBOX": ["ABS", "PETG", "PLA"],
        "Overture": ["ABS", "PLA"],
        "Polymaker": ["ABS", "PLA", "PLA-HT"],
    },
}

# Slot data from box_extras, injected into the `items` loop where m is the slot (0..15)
# and C/w/S are colour, material and vendor.
SLOT_FROM_BOX_EXTRAS = (
    "/*" + VERSION + "*/{const fi=this.$store.state.printer.printer.box_extras?.boxes?.[Math.floor(m/4)]"
    "?.filament_info?.[m%4];if(fi){const fc=fi.color_rgb_str?.[0];"
    "fc&&(C=\"#\"+String(fc).replace(\"#\",\"\"));w=fi.filament_str||w;S=fi.vendor_str||S}}"
)

# Methods added to the panel component. qdNewFw tells whether the selected slot (box slot or the external
# spool, 16) has data in the new format; qdDb picks the material list for the installed nozzle (0.4 if unknown);
# qdRack shows the external spool from multi_color_controller.extra; qdUpdateSlot fills the fields that were not
# changed from the current slot state and sends the command in QIDI Studio's format.
SLOT_METHODS = (
    "qdNewFw(){const p=this.$store.state.printer.printer;return this.selectIndex<16"
    "?!!p.box_extras?.boxes?.[0]?.filament_info:this.selectIndex===16&&!!p.multi_color_controller?.extra?.filament_info}"
    "qdDb(){const all=" + json.dumps(FILAMENT_DB, separators=(",", ":")) + ","
    "d=parseFloat(this.$store.state.printer.printer.configfile?.settings?.extruder?.nozzle_diameter);"
    "return all[Object.keys(all).find(k=>Math.abs(parseFloat(k)-d)<.01)??\"0.4\"]}"
    "qdRack(r){const fi=this.$store.state.printer.printer.multi_color_controller?.extra?.filament_info;"
    "if(!fi?.filament_str)return r;const fc=fi.color_rgb_str?.[0];"
    "return{...r,color:fc?\"#\"+String(fc).replace(\"#\",\"\"):r.color,filament:fi.filament_str,vendor:fi.vendor_str||r.vendor}}"
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
    (
        ',t[17]={label:"",color:"#00000000",filament:"",vendor:"",isRotating:!1},t}',
        ',t[16]=this.qdRack(t[16]),t[17]={label:"",color:"#00000000",filament:"",vendor:"",isRotating:!1},t}',
    ),
    # Pre-print check with the box disabled: e_endstop_state / b_endstop_state are no longer in box_extras.
    # Fall back to the external filament sensor and multi_color_controller (idea from Greg-LFT's Q2 patch).
    (
        "get isOkPrinter(){return this.enableBox===!1?this.$store.state.printer.printer.box_extras.e_endstop_state===1"
        "?this.$store.state.printer.printer.box_extras.b_endstop_state===0?",
        "get isOkPrinter(){const qp=this.$store.state.printer.printer,qx=qp.box_extras||{},"
        "qe=qx.e_endstop_state??(qp[\"filament_switch_sensor filament_switch_sensor\"]?.filament_detected?1:0),"
        "qb=qx.b_endstop_state??qp.multi_color_controller?.box?.b_endstop_state;"
        "return this.enableBox===!1?qe===1?qb===0?",
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
        # multi_color_controller sends only changed fields at any depth (e.g. extra.filament_info with just
        # the colour), so its nested objects are merged recursively; arrays are replaced.
        "t[s]!==e.payload[s]&&$.set(r.printer[e.key],s,e.key===\"multi_color_controller\""
        "?function qm(a,b){if(!a||!b||typeof a!=\"object\"||typeof b!=\"object\"||Array.isArray(a)||Array.isArray(b))"
        "return b;const o={...a};for(const k in b)o[k]=qm(a[k],b[k]);return o}(t[s],e.payload[s]):e.payload[s])",
    ),
]


def sw_replacements(bundle):
    return [('{"revision":null,"url":"' + bundle + '"}', '{"revision":"' + VERSION + '","url":"' + bundle + '"}')]


class PatchError(Exception):
    pass


def fail(msg):
    raise PatchError(msg)


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


def fluidd_version(root):
    path = root / ".version"
    return read_file(path).strip() if path.is_file() else "unknown version"


def apply_replacements(path, text, replacements, found):
    for old, new, *expected in replacements:
        expected = expected[0] if expected else 1
        count = text.count(old)
        if count != expected:
            fail(
                "This Fluidd build is not the one the patch was made for. Nothing was changed.\n"
                f"  Found:    Fluidd {found}\n"
                f"  Expected: {TARGET}\n"
                f"  Firmware: {qidi_packages()}\n"
                f"  Detail:   {path.name}: expected {expected} match(es) of `{old[:80]}`, found {count}\n"
                f"Run the script with --check and open an issue at {REPO}/issues if you think it should work."
            )
        text = text.replace(old, new)
    return text


def plan_patch(root):
    """Return (bundle, current texts, patched texts); patched is None when this version is already applied.
    Every patched file is built before anything is written, so a mismatch leaves the files untouched."""
    bundle = find_bundle(root)
    found = f"{fluidd_version(root)} ({bundle})"
    files = [(root / bundle, BUNDLE_REPLACEMENTS), (root / "sw.js", sw_replacements(bundle))]
    current = {path: read_file(path) for path, _ in files}
    if all(VERSION in text for text in current.values()):
        return bundle, current, None
    return bundle, current, {path: apply_replacements(path, original_text(path), repl, found) for path, repl in files}


def patch(root, dry_run):
    _, current, patched = plan_patch(root)
    if patched is None:
        print(f"Already patched with {VERSION}, nothing to do.")
        return
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


def moonraker_get(base, path):
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=10) as response:
        return json.load(response)["result"]


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest() if path.is_file() else "missing"


def qidi_packages():
    try:
        out = subprocess.run(["dpkg-query", "-W", "-f=${Package} ${Version}\n"], capture_output=True, text=True,
                             timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown (dpkg-query not available)"
    pkgs = [line for line in out.splitlines() if re.match(r"(qd|qidi)[-_]", line, re.I)]
    return ", ".join(pkgs) or "none found"


def check_fluidd(root, rows, problems):
    for name in (".version", "release_info.json"):
        if (root / name).is_file():
            rows.append(("Fluidd " + name, read_file(root / name).strip()[:120]))
    try:
        bundle, current, patched = plan_patch(root)
    except PatchError as e:
        rows.append(("Fluidd patch", "does NOT fit"))
        problems.append("Fluidd: " + " ".join(str(e).split()))
        return
    rows.append(("Fluidd bundle", f"{bundle} md5 {md5(root / bundle)}, sw.js md5 {md5(root / 'sw.js')}"))
    if patched is None:
        state = f"patched with {VERSION}"
    elif any(MARKER in text for text in current.values()):
        state = "patched with an older version, update fits"
    else:
        state = "not patched, patch fits"
    rows.append(("Fluidd patch", state))


def check_printer(base, rows, problems):
    """Add the firmware side to the report; return False when Moonraker could not be read."""
    try:
        info = moonraker_get(base, "/printer/info")
        objects = moonraker_get(base, "/printer/objects/list")["objects"]
        commands = moonraker_get(base, "/printer/gcode/help")
        status = moonraker_get(base, "/printer/objects/query?box_extras&multi_color_controller&save_variables")["status"]
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        rows.append(("Moonraker", f"not reachable at {base} ({e})"))
        return False
    rows.append(("Klipper", f"{info.get('software_version', '?')} (state: {info.get('state', '?')})"))
    rows.append(("Box objects", ", ".join(o for o in objects if re.match(r"box|multi_color", o)) or "none"))

    missing = [c for c in NEW_COMMANDS if c not in commands]
    rows.append(("New box commands", "all present" if not missing else "missing: " + ", ".join(missing)))
    rows.append(("Old box commands", ", ".join(c for c in OLD_COMMANDS if c in commands) or "none (removed)"))
    if missing:
        problems.append("Firmware lacks commands the patched buttons send: " + ", ".join(missing))

    boxes = (status.get("box_extras") or {}).get("boxes") or []
    online = [b for b in boxes if b.get("is_online")]
    infos = [fi for b in online for fi in (b.get("filament_info") or [])]
    rows.append(("Boxes online", f"{len(online)} of {len(boxes)}, {len(infos)} slots with filament_info"))
    if not infos:
        problems.append("box_extras.boxes[].filament_info is missing - the patch reads slot materials from it.")
    elif any(k not in infos[0] for k in FILAMENT_INFO_KEYS):
        problems.append("filament_info lacks some of " + ", ".join(FILAMENT_INFO_KEYS))

    mcc_box = (status.get("multi_color_controller") or {}).get("box") or {}
    rows.append(("b_endstop_state", "present" if "b_endstop_state" in mcc_box else "missing"))
    if "b_endstop_state" not in mcc_box:
        problems.append("multi_color_controller.box.b_endstop_state is missing - Unload may stay disabled.")

    slot0 = ((status.get("save_variables") or {}).get("variables") or {}).get("filament_slot0")
    rows.append(("filament_slot0 format", "new (filament ID)" if isinstance(slot0, str) else f"old ({slot0!r})"))
    return True


def check(root, moonraker):
    rows = [("Script", VERSION), ("Python", platform.python_version()), ("QIDI packages", qidi_packages())]
    problems = []
    check_fluidd(root, rows, problems)
    printer_read = check_printer(moonraker, rows, problems)
    if not printer_read:
        problems.append("The printer could not be read from Moonraker, so the firmware side was not checked. "
                        "Run --check on the printer itself while Klipper is running.")

    print("### qidi_fluidd_box_fix --check report\n")
    print("| Item | Value |\n|---|---|")
    for name, value in rows:
        print(f"| {name} | {str(value).replace('|', '/')} |")
    print()
    if problems:
        # With only the unread printer to report, nothing incompatible was found yet.
        print("**Result: incomplete**\n" if len(problems) == 1 and not printer_read
              else "**Result: NOT compatible as is**\n")
        for p in problems:
            print(f"- {p}")
    else:
        print("**Result: looks compatible**")
    print(f"\nNothing was changed. To report, open an issue at {REPO}/issues and paste this whole report.")


def main():
    parser = argparse.ArgumentParser(description="Fix the Fluidd box panel for QIDI Max4 firmware 01.01.07.01")
    parser.add_argument("--fluidd-dir", default=DEFAULT_DIR, help=f"Fluidd directory (default {DEFAULT_DIR})")
    parser.add_argument("--restore", action="store_true", help="restore the original Fluidd files")
    parser.add_argument("--dry-run", action="store_true", help="only check whether the patch fits")
    parser.add_argument("--check", action="store_true", help="read-only compatibility report for a GitHub issue")
    parser.add_argument("--moonraker", default=DEFAULT_MOONRAKER, help=f"Moonraker URL for --check "
                                                                       f"(default {DEFAULT_MOONRAKER})")
    args = parser.parse_args()

    root = pathlib.Path(args.fluidd_dir)
    try:
        if args.check:
            check(root, args.moonraker)
        elif args.restore:
            restore(root)
        else:
            patch(root, args.dry_run)
    except PatchError as e:
        sys.exit(f"ERROR: {e}")
    except PermissionError as e:
        sys.exit(f"ERROR: {e}\nRun the script with sudo.")


if __name__ == "__main__":
    main()
