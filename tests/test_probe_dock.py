#!/usr/bin/env python3
"""Static checks for the Klicky/Euclid home-dock pickup & probe-sensed dropoff.

Context: the probe dock rides on the moving gantry at the E1 (carriage 0) X
endstop, so PICKUP is a plain "home X". The blocker is on the static extrusion,
so its Z varies run-to-run and DROPOFF probe-senses it live. Because a
gcode_macro renders its whole template before running any command, the PROBE
(sense) and the read of printer.probe.last_z_result MUST live in different
macros — otherwise the read sees a stale result. These tests lock that in.
"""

import re
import unittest
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
EUCLID = BASE / "EuclidUtilities.cfg"
HOST_DEPS = BASE / "macros" / "_host_deps.cfg"


def macro_body(text: str, name: str) -> str:
    """Return the body of [gcode_macro <name>] up to the next config section."""
    pattern = re.compile(r"^\[gcode_macro\s+" + re.escape(name) + r"\]", re.MULTILINE)
    match = pattern.search(text)
    assert match, f"macro {name} not found"
    start = match.end()
    nxt = re.search(r"^\[", text[start:], re.MULTILINE)
    return text[start:start + nxt.start()] if nxt else text[start:]


def commands(body: str) -> list[str]:
    """Command lines only (comments and blank lines stripped)."""
    out = []
    for line in body.splitlines():
        code = line.split("#", 1)[0].strip()
        if code:
            out.append(code)
    return out


class ProbePickupTests(unittest.TestCase):
    def test_pickup_homes_x_only_never_full_or_z_home(self) -> None:
        cmds = commands(macro_body(EUCLID.read_text(), "PROBE_PICKUP"))
        # Must home carriage 0's X...
        self.assertIn("SET_DUAL_CARRIAGE CARRIAGE=0", cmds)
        self.assertIn("G28 X", cmds)
        # ...but NEVER a bare/full G28 or a Z home — the probe isn't attached yet,
        # and Z homes via the probe, so a Z-inclusive home would fail.
        self.assertNotIn("G28", cmds)
        self.assertNotIn("G28 Z", cmds)
        self.assertNotIn("HOME_IF_NOT", cmds)

    def test_pickup_guards_copy_mirror_mode(self) -> None:
        body = macro_body(EUCLID.read_text(), "PROBE_PICKUP")
        self.assertIn("_IDEX_MODE", body)
        self.assertIn("idex_mode", body)

    def test_pickup_verifies_attach(self) -> None:
        self.assertIn("PROBEON", commands(macro_body(EUCLID.read_text(), "PROBE_PICKUP")))


class ProbeDropoffTests(unittest.TestCase):
    def test_dropoff_verifies_probe_then_delegates(self) -> None:
        cmds = commands(macro_body(EUCLID.read_text(), "PROBE_DROPOFF"))
        self.assertIn("QUERY_PROBE", cmds)
        self.assertIn("_PROBE_DROPOFF_SENSE", cmds)

    def test_sense_stage_checks_probe_attached_before_probing(self) -> None:
        body = macro_body(EUCLID.read_text(), "_PROBE_DROPOFF_SENSE")
        # NC wiring: attached => last_query False. Guard aborts if detached.
        self.assertIn("printer.probe.last_query", body)

    def test_probe_and_result_read_are_in_separate_macros(self) -> None:
        """The render-order invariant: PROBE runs in _SENSE, last_z_result is
        read in _STRIP. Colocating them would read a stale probe result."""
        sense = macro_body(EUCLID.read_text(), "_PROBE_DROPOFF_SENSE")
        strip = macro_body(EUCLID.read_text(), "_PROBE_DROPOFF_STRIP")
        # The bare PROBE command is in _SENSE, not _STRIP.
        self.assertIn("PROBE", commands(sense))
        self.assertNotIn("PROBE", commands(strip))
        # last_z_result is READ IN CODE (not merely mentioned in a comment) in
        # _STRIP, not _SENSE — so compare comment-stripped command text.
        sense_code = "\n".join(commands(sense))
        strip_code = "\n".join(commands(strip))
        self.assertIn("last_z_result", strip_code)
        self.assertNotIn("last_z_result", sense_code)

    def test_geometry_is_endstop_relative(self) -> None:
        sense = macro_body(EUCLID.read_text(), "_PROBE_DROPOFF_SENSE")
        strip = macro_body(EUCLID.read_text(), "_PROBE_DROPOFF_STRIP")
        # Dock X is read live from the endstop; sense/release are +X offsets.
        self.assertIn("stepper_x.position_endstop", sense)
        self.assertIn("probe_dock_sense_xoffset", sense)
        self.assertIn("probe_dock_release", strip)

    def test_engagement_z_is_clamped_to_z_min(self) -> None:
        strip = macro_body(EUCLID.read_text(), "_PROBE_DROPOFF_STRIP")
        # engage_z must be clamped >= stepper_z.position_min (never command below).
        self.assertIn("stepper_z.position_min", strip)

    def test_dropoff_verifies_detach(self) -> None:
        self.assertIn("PROBEOFF", commands(macro_body(EUCLID.read_text(), "_PROBE_DROPOFF_STRIP")))


class DockConfigTests(unittest.TestCase):
    def test_old_absolute_dock_vars_are_retired(self) -> None:
        for cfg in BASE.rglob("*.cfg"):
            text = cfg.read_text()
            for old in ("probe_pickup_xpos", "probe_pickup_ypos", "probe_pickup_zpos"):
                self.assertNotIn(old, text, f"{old} still referenced in {cfg.name}")

    def test_lnlos_defines_new_dock_vars(self) -> None:
        text = HOST_DEPS.read_text()
        for var in ("probe_dock_sense_xoffset", "probe_dock_release",
                    "probe_dock_zoffset", "probe_pickup_zraise"):
            self.assertRegex(text, r"(?m)^\s*variable_" + var + r"\s*:")


class ProbeWrapperTests(unittest.TestCase):
    def _full_homes_between(self, macro: str, calibrate: str) -> None:
        cmds = commands(macro_body(EUCLID.read_text(), macro))
        self.assertIn("PROBE_PICKUP", cmds)
        self.assertIn("G28", cmds)
        self.assertIn(calibrate, cmds)
        # G28 must sit AFTER pickup and BEFORE the calibrate step.
        self.assertLess(cmds.index("PROBE_PICKUP"), cmds.index("G28"))
        self.assertLess(cmds.index("G28"), cmds.index(calibrate))

    def test_prepare_bedmesh_full_homes_after_pickup(self) -> None:
        self._full_homes_between("_Prepare_BedMesh", "BED_MESH_CALIBRATE")

    def test_auto_probe_full_homes_after_pickup(self) -> None:
        self._full_homes_between("_AUTO_PROBE", "SCREWS_TILT_CALCULATE")


if __name__ == "__main__":
    unittest.main()
