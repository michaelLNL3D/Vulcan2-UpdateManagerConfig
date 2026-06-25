#!/usr/bin/env python3
"""Static checks for the E2 offset calibration print macro."""

import ast
import re
import unittest
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
MACRO = BASE / "macros" / "E2OffsetTest.cfg"
GROUP_SCRIPT = BASE / "scripts" / "setup_mainsail_macro_groups.py"
KLIPPERSCREEN = BASE / "Klipperscreen_LNL.conf"


class E2OffsetTestMacroTests(unittest.TestCase):
    def macro_text(self) -> str:
        return MACRO.read_text()

    def test_macro_accepts_filament_input_and_heats_both_tools(self) -> None:
        text = self.macro_text()

        self.assertIn("[gcode_macro IDEX_OFFSET_TEST]", text)
        self.assertIn("[gcode_macro _IDEX_OFFSET_TEST_START]", text)
        self.assertIn("FILAMENT=<PLA|PETG|ABS|ASA|TPU|NYLON|PC>", text)
        self.assertIn("params.FILAMENT|default(\"PLA\")|upper", text)
        self.assertIn("BED_TEMP", text)
        self.assertIn("HOTEND_TEMP", text)
        self.assertIn("M104 T0 S{hotend}", text)
        self.assertIn("M104 T1 S{hotend}", text)
        self.assertIn("M140 S{bed}", text)
        self.assertIn("M190 S{bed}", text)
        self.assertIn("M109 T0 S{hotend}", text)
        self.assertIn("M109 T1 S{hotend}", text)
        self.assertIn("SET_GCODE_VARIABLE MACRO=_TOOL_TEMPS VARIABLE=t0 VALUE={hotend}", text)
        self.assertIn("SET_GCODE_VARIABLE MACRO=_TOOL_TEMPS VARIABLE=t1 VALUE={hotend}", text)

    def test_public_macro_prompts_for_filament_before_starting(self) -> None:
        text = self.macro_text()

        public_body = text.split("[gcode_macro IDEX_OFFSET_TEST]", 1)[1].split(
            "[gcode_macro _IDEX_OFFSET_TEST_START]", 1
        )[0]
        self.assertIn("{% if params.FILAMENT is defined %}", public_body)
        self.assertIn("_IDEX_OFFSET_TEST_START {rawparams}", public_body)
        self.assertIn("action:prompt_begin E2 Offset Test", public_body)
        self.assertIn("action:prompt_text Select the loaded filament to start the test.", public_body)
        for filament in ["PLA", "PETG", "ABS", "ASA", "TPU", "NYLON", "PC"]:
            self.assertIn(
                f"action:prompt_button {filament}|_IDEX_OFFSET_TEST_START FILAMENT={filament}",
                public_body,
            )
        self.assertIn("action:prompt_footer_button Cancel|_PROMPT_CLOSE|error", public_body)

    def test_macro_opens_offset_panel_and_starts_with_e1(self) -> None:
        text = self.macro_text()

        self.assertIn("_IDEX_MODE MODE=0", text)
        self.assertIn("SET_DUAL_CARRIAGE CARRIAGE=0 MODE=PRIMARY", text)
        self.assertIn("SET_DUAL_CARRIAGE CARRIAGE=1 MODE=PRIMARY", text)
        self.assertIn("CLEAR_GCODE_OFFSETS", text)
        self.assertIn("IDEX_OFFSET_PANEL", text)
        panel = text.index("IDEX_OFFSET_PANEL")
        layer_loop = text.index("{% for layer in range(1, 51) %}")
        self.assertLess(panel, text.index("T0", panel))
        self.assertLess(text.index("T0", panel), layer_loop)

    def test_macro_prints_50_layer_10mm_cube_and_switches_every_five_layers(self) -> None:
        text = self.macro_text()

        self.assertRegex(text, r"variable_size:\s*10(?:\.0)?")
        self.assertRegex(text, r"variable_layer_height:\s*0\.2")
        self.assertIn("{% for layer in range(1, 51) %}", text)
        self.assertIn("{% set tool = ((layer - 1) // 5) % 2 %}", text)
        self.assertIn("{% if tool == 0 %}", text)
        self.assertIn("T0", text)
        self.assertIn("{% else %}", text)
        self.assertIn("T1", text)
        self.assertIn("G1 Z{layer * layer_height}", text)

    def test_macro_uses_two_walls_and_diagonal_cross_infill(self) -> None:
        text = self.macro_text()

        self.assertRegex(text, r"variable_wall_count:\s*2")
        self.assertIn("{% for wall in range(wall_count) %}", text)
        self.assertIn("wall * line_width", text)
        self.assertIn("{% if layer % 2 == 1 %}", text)
        self.assertIn("G1 X{infill_max} Y{infill_y_max}", text)
        self.assertIn("G1 X{infill_max} Y{infill_y_min}", text)

    def test_macro_is_in_mainsail_idex_group(self) -> None:
        tree = ast.parse(GROUP_SCRIPT.read_text())
        groups = None
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "GROUPS":
                        groups = ast.literal_eval(node.value)
        self.assertIsNotNone(groups)
        self.assertIn("IDEX_OFFSET_TEST", groups["IDEX"])

    def test_macro_is_available_from_klipperscreen_idex_menu(self) -> None:
        text = KLIPPERSCREEN.read_text()

        self.assertIn("[menu __main IDEX offsettest]", text)
        self.assertIn("name: E2 Offset Test", text)
        self.assertIn('params: {"script":"IDEX_OFFSET_TEST"}', text)

    def test_macro_names_are_valid_for_klipper_dispatcher(self) -> None:
        cfg_files = sorted((BASE / "macros").glob("*.cfg"))
        cfg_files += [BASE / "scripts" / "setup_mainsail_macro_groups.py"]
        invalid_names = []

        macro_pattern = re.compile(r"^\[gcode_macro\s+([^\]]+)\]", re.MULTILINE)
        for cfg_file in cfg_files:
            text = cfg_file.read_text()
            for name in macro_pattern.findall(text):
                if re.search(r"\d(?=.*\D)", name):
                    invalid_names.append(f"{cfg_file.relative_to(BASE)}:{name}")

        self.assertEqual([], invalid_names)


if __name__ == "__main__":
    unittest.main()
