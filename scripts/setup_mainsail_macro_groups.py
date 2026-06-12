#!/usr/bin/env python3
"""Provision Mainsail dashboard macro groups via the Moonraker database API.

PROVISIONING TOOL — run once per golden-image build (or to restore a wiped
database). Do NOT wire this into startup: it overwrites the `mainsail.macros`
database key, which would clobber any macro-layout tweaks made in the UI.

Usage:
    ./setup_mainsail_macro_groups.py [host]      # default host: localhost:7125

What it does:
  1. Backs up the current `mainsail.macros` DB key (stdout + backup file).
  2. Writes macro groups (Filament / Probe & Calibration / IDEX / Utilities)
     and sets macro mode to 'expert'. In expert mode Mainsail shows ONLY
     grouped macros on the dashboard — everything else stays callable but
     gains no button.
  3. Verifies the write by reading the key back.

Touches ONLY the Moonraker database (HTTP API) — no files, no git repos, so
the Moonraker update manager is unaffected. Schema matches Mainsail v2.17
(src/store/gui/macros/types.ts). Refresh the browser after running.
"""

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# uuid5 namespace: stable IDs per group name, so re-runs replace rather than
# duplicate groups (layout panels are named macrogroup_<id>).
NS = uuid.uuid5(uuid.NAMESPACE_DNS, "vulcan2.lnl3d.macrogroups")

GROUPS = {
    "Filament": [
        "LOAD_FILAMENT",
        "UNLOAD_FILAMENT",
        "M600",
    ],
    "Probe & Calibration": [
        "PROBE_PICKUP",
        "PROBE_DROPOFF",
        "BED_MESH_CALIBRATE",
        "SCREWS_TILT_CALCULATE",
        "calibrate_z_e2",
    ],
    "IDEX": [
        "ACTIVATE_COPY_MODE",
        "ACTIVATE_MIRROR_MODE",
        "ACTIVATE_DUAL_MATERIAL_MODE",
        "ACTIVATE_DUPLICATION_MODE",
        "ACTIVATE_TOOLCHANGER_MODE",
        "IDEX_OFFSET_PANEL",
        "SHOW_IDEX_OFFSETS",
    ],
    "Utilities": [
        "PID_ALL",
        "PID_EXTRUDERS",
        "PID_BED",
        "MAINTENANCE_STATUS",
        "SUPPORT_INFO",
        "LNLOS",
    ],
}


def api(host: str, path: str, payload=None):
    url = f"http://{host}{path}"
    if payload is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)["result"]


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost:7125"
    if ":" not in host:
        host += ":7125"

    # --- sanity: Moonraker reachable, list defined macros -------------------
    try:
        objects = api(host, "/printer/objects/list")["objects"]
    except (urllib.error.URLError, OSError) as exc:
        print(f"ERROR: cannot reach Moonraker at {host}: {exc}")
        return 1
    defined = {
        o[len("gcode_macro ") :] for o in objects if o.startswith("gcode_macro ")
    }
    for group, macros in GROUPS.items():
        for name in macros:
            if name not in defined and name.upper() not in defined:
                print(f"WARNING: '{name}' ({group}) is not currently defined")

    # --- backup existing key ------------------------------------------------
    try:
        old = api(host, "/server/database/item?namespace=mainsail&key=macros")
        old_value = old["value"]
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        old_value = None  # fresh install: key absent
    print("Previous mainsail.macros value:")
    print(json.dumps(old_value, indent=2))
    backup_dir = Path.home() / "printer_data" / "backup"
    backup_dir = backup_dir if backup_dir.parent.exists() else Path("/tmp")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"mainsail_macros_{time.strftime('%Y%m%d_%H%M%S')}.json"
    backup.write_text(json.dumps(old_value, indent=2))
    print(f"Backup written to {backup}\n")

    # --- build & write new value (Mainsail v2.17 schema) --------------------
    macrogroups = {}
    for pos_base, (group, macros) in enumerate(GROUPS.items()):
        gid = str(uuid.uuid5(NS, group))
        macrogroups[gid] = {
            "id": gid,
            "name": group,
            "color": "primary",
            "showInStandby": True,
            "showInPrinting": True,
            "showInPause": True,
            "macros": [
                {
                    "pos": i + 1,
                    "name": name,
                    "color": "group",
                    "showInStandby": True,
                    "showInPrinting": True,
                    "showInPause": True,
                }
                for i, name in enumerate(macros)
            ],
        }
    value = {"mode": "expert", "hiddenMacros": [], "macrogroups": macrogroups}
    api(
        host,
        "/server/database/item",
        {"namespace": "mainsail", "key": "macros", "value": value},
    )

    # --- verify ---------------------------------------------------------------
    readback = api(host, "/server/database/item?namespace=mainsail&key=macros")
    if readback["value"] != value:
        print("ERROR: read-back mismatch — database write did not stick")
        return 1
    print(f"OK: wrote {len(macrogroups)} macro groups "
          f"({sum(len(m) for m in GROUPS.values())} macros) in expert mode.")
    print("Refresh the Mainsail page to see the new sections.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
