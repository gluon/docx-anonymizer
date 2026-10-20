"""The one button that carries each screen must be legible.

Qt asks the platform to draw a default button, and macOS drew the main
action light grey on white: it read as disabled. Nothing in the suite
could see that, and nothing can: there is no display here, and the theme
that painted it is not this program's.

So the colours stopped being the theme's business, and legibility
stopped being a matter of looking at the screen. The ratios below are
the WCAG 2.1 contrast formula, computed from the stylesheet the window
actually ships.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

GUI = (Path(__file__).resolve().parents[1] / "src" / "dxanon" / "gui.py").read_text(
    encoding="utf-8"
)

#: 4.5 is the WCAG AA threshold for ordinary text, 3.0 for large or bold
#: text. The buttons are bold and 40 pixels high, so AA is met at 3.0;
#: this asks for the stricter number, because the screens are read by
#: someone working, in a hurry, on whatever screen is in front of them.
AA_NORMAL = 4.5


def _luminance(colour: str) -> float:
    r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = channel(r), channel(g), channel(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(first: str, second: str) -> float:
    a, b = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def constant(name: str) -> str:
    """A colour constant, read from the source rather than imported.

    PySide6 is not installed in every environment this suite runs in, and
    importing the window would skip these checks exactly where they are
    most needed: the machine that has no display is also the one that
    cannot look at the button.
    """
    found = re.search(rf'^{name} = "(#[0-9a-fA-F]{{6}})"', GUI, re.M)
    assert found, name
    return found.group(1)


def rule(selector: str) -> dict[str, str]:
    """The declarations of one selector in the shipped stylesheet."""
    block = re.search(selector + r"\s*{{?(.*?)}}?\s*\n", GUI, re.S)
    assert block, selector
    return dict(
        (key.strip(), value.strip())
        for key, _, value in (line.partition(":") for line in block.group(1).split(";"))
        if key.strip()
    )


class KnownGoodFormula(unittest.TestCase):
    """The formula itself, against two ratios published by the W3C."""

    def test_black_on_white_is_twenty_one(self):
        self.assertAlmostEqual(contrast("#000000", "#ffffff"), 21.0, places=2)

    def test_mid_grey_on_white(self):
        self.assertAlmostEqual(contrast("#767676", "#ffffff"), 4.54, places=2)


class ThePrimaryButton(unittest.TestCase):
    def test_the_label_is_legible_on_the_button(self):
        self.assertGreaterEqual(
            contrast(constant("PRIMARY_TEXT"), constant("PRIMARY_BACKGROUND")), AA_NORMAL,
        )

    def test_the_button_stands_out_from_the_window(self):
        """Grey on white was the defect; white on grey would be the same."""
        self.assertGreaterEqual(contrast(constant("PRIMARY_BACKGROUND"), "#ffffff"), 3.0)

    def test_every_painted_state_stays_legible(self):
        for selector in (r"QPushButton:hover", r"QPushButton:pressed",
                         r"QPushButton:disabled"):
            declarations = rule(selector)
            background = declarations["background-color"]
            text = declarations.get("color", "#ffffff")
            with self.subTest(selector=selector):
                self.assertGreaterEqual(contrast(text, background), AA_NORMAL)

    def test_a_disabled_button_does_not_look_like_an_enabled_one(self):
        """Qt greys only the label unless the state is spelled out."""
        disabled = rule(r"QPushButton:disabled")["background-color"]
        self.assertGreaterEqual(contrast(disabled, constant("PRIMARY_BACKGROUND")), 3.0)

    def test_the_colours_are_not_left_to_the_platform(self):
        self.assertIn("setStyleSheet(PRIMARY_STYLE)", GUI)
        self.assertEqual(GUI.count("primary(QPushButton("), 3)
        self.assertIn("primary(\n", GUI)


if __name__ == "__main__":
    unittest.main()
