#!/usr/bin/env python3
"""Static checks for the cancel-print probe fix and the consolidated homing lift.

Context: on this machine Z homes via the Euclid probe, but printing requires the
probe REMOVED. The old cancel path ran ACTIVATE_DUAL_MATERIAL_MODE, which does a
bare (full) G28 — homing Z and therefore tripping the probe-attached guard every
time a print was cancelled. The cancel path must restore IDEX state WITHOUT
re-homing Z (the machine is already homed mid-print).
"""

import re
import unittest
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
PRINT_START_END = BASE / "macros" / "PrintStartEnd.cfg"
IDEX = BASE / "macros" / "idex.cfg"
SAFEHOME = BASE / "macros" / "safehome.cfg"
EUCLID = BASE / "EuclidUtilities.cfg"


def macro_body(text: str, name: str) -> str:
    """Return the body of [gcode_macro <name>] up to the next config section."""
    pattern = re.compile(r"^\[gcode_macro\s+" + re.escape(name) + r"\]", re.MULTILINE)
    match = pattern.search(text)
    assert match, f"macro {name} not found"
    start = match.end()
    nxt = re.search(r"^\[", text[start:], re.MULTILINE)
    return text[start:start + nxt.start()] if nxt else text[start:]


class CancelPrintProbeFixTests(unittest.TestCase):
    def test_cancel_cleanup_does_not_full_home_or_require_probe(self) -> None:
        body = macro_body(PRINT_START_END.read_text(), "_VULCAN_CANCEL_CLEANUP")
        # Commands only — ignore comments so doc text can mention these names.
        commands = [line.split("#", 1)[0].strip() for line in body.splitlines()]
        # Must NOT call ACTIVATE_DUAL_MATERIAL_MODE (it does a full, probe-homing
        # G28) nor issue a bare full G28 directly — that is the cancel bug.
        self.assertNotIn("ACTIVATE_DUAL_MATERIAL_MODE", commands)
        self.assertNotIn("G28", commands)
        # Restores IDEX state via the no-home helper instead.
        self.assertIn("_APPLY_DUAL_MATERIAL_MODE", commands)
        # X re-home is fine — X homing never needs the probe.
        self.assertIn("G28 X", commands)

    def test_apply_dual_material_mode_helper_has_no_homing(self) -> None:
        text = IDEX.read_text()
        self.assertIn("[gcode_macro _APPLY_DUAL_MATERIAL_MODE]", text)
        helper = macro_body(text, "_APPLY_DUAL_MATERIAL_MODE")
        self.assertNotIn("G28", helper)
        self.assertIn("CLEAR_GCODE_OFFSETS", helper)
        self.assertIn("ACTIVATE_EXTRUDER EXTRUDER=extruder", helper)
        self.assertIn("SET_DUAL_CARRIAGE CARRIAGE=0 MODE=PRIMARY", helper)
        self.assertIn("_IDEX_MODE MODE=0", helper)

    def test_activate_dual_material_mode_still_homes_then_applies(self) -> None:
        body = macro_body(IDEX.read_text(), "ACTIVATE_DUAL_MATERIAL_MODE")
        # Interactive mode switch keeps homing, then delegates to the helper.
        self.assertIn("G28", body)
        self.assertIn("_APPLY_DUAL_MATERIAL_MODE", body)

    def test_restore_idex_mode_dual_material_does_not_full_home(self) -> None:
        body = macro_body(IDEX.read_text(), "_RESTORE_IDEX_MODE")
        commands = [line.split("#", 1)[0].strip() for line in body.splitlines()]
        # Runs at the end of print start, when the probe is already removed —
        # must restore dual-material mode WITHOUT a probe-homing full G28.
        self.assertNotIn("ACTIVATE_DUAL_MATERIAL_MODE", commands)
        self.assertIn("_APPLY_DUAL_MATERIAL_MODE", commands)


class HomingSingleLiftTests(unittest.TestCase):
    def test_safe_z_home_zhop_enabled_for_probe_pickup(self) -> None:
        text = SAFEHOME.read_text()
        # DECISION CHANGE (klicky home-dock): z_hop RE-ENABLED to 15. PROBE_PICKUP
        # homes X only (probe not attached), which takes G28's plain "G28.1 {axes}"
        # path — no explicit lift — and Z is UNHOMED, so a macro-level G1 Z+ is
        # impossible without [force_move]. z_hop is the only mechanism that lifts
        # the unhomed Z before the carriage traverses to the dock, clearing the
        # blocker/bed on a cold, low-Z start. Trade-off: a second lift on a
        # Z-inclusive re-home (alongside the G28 macro's explicit G1 Z15) — extra
        # Z travel only. See macros/safehome.cfg for the full rationale.
        self.assertRegex(text, r"(?m)^\s*z_hop:\s*15\b")

    def test_g28_macro_keeps_single_explicit_lift(self) -> None:
        body = macro_body(EUCLID.read_text(), "G28")
        # Exactly one explicit Z lift, after the Y-home block, before the traverse.
        self.assertEqual(len(re.findall(r"G1 Z15\b", body)), 1)


if __name__ == "__main__":
    unittest.main()
