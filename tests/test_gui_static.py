"""What can be checked about the window without a display.

The suite runs headless and PySide6 is not installed in every
environment, so the window is never shown here. That is a real gap and
it is stated in the README: until someone opens it on Windows, its
behaviour is unverified.

These checks are what remains possible, and they catch the mistakes that
actually happen when a file is written but never run: a syntax error, a
name imported and never used, a call into the engine that no longer
exists, and logic quietly creeping out of the tested layers into the
untested one.
"""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

GUI = Path(__file__).resolve().parents[1] / "src" / "dxanon" / "gui.py"


class StaticChecks(unittest.TestCase):
    def setUp(self):
        self.source = GUI.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_it_parses(self):
        self.assertTrue(self.tree.body)

    def test_every_import_is_used(self):
        """An unused widget import usually means a half-finished screen."""
        used = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)}
        used |= {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "__future__":
                    continue
                for alias in node.names:
                    name = alias.asname or alias.name
                    self.assertTrue(
                        name in used or self.source.count(name) > 1,
                        f"{name} is imported and never used",
                    )

    def test_it_only_calls_functions_the_engine_actually_has(self):
        from dxanon import engine, plaintext, workflow

        expected = {
            "engine": {"anonymize", "deanonymize"},
            "plaintext": {"anonymize", "deanonymize"},
            "workflow": {"build"},
        }
        modules = {"engine": engine, "plaintext": plaintext, "workflow": workflow}
        for module_name, attributes in expected.items():
            for attribute in attributes:
                self.assertTrue(
                    hasattr(modules[module_name], attribute),
                    f"gui calls {module_name}.{attribute}, which no longer exists",
                )

    def test_the_window_stays_thin(self):
        """Logic in here is logic no test covers.

        A budget rather than a rule: if the window grows past it, the
        reason is usually a decision that belongs in workflow.py, where
        it can be tested.
        """
        statements = sum(isinstance(n, (ast.If, ast.For, ast.While)) for n in ast.walk(self.tree))
        self.assertLess(statements, 40, "branching logic is accumulating in the untested layer")

    def test_the_refusal_path_tells_the_user_nothing_was_written(self):
        """The one message that must not be reassuring by accident."""
        self.assertIn("rien n'a été écrit", self.source)

    def test_images_are_reported_to_the_user(self):
        self.assertIn("image", self.source.lower())


class WhatIsOnScreen(unittest.TestCase):
    """Standing text has a budget, because nobody reads a wall of it.

    The home page used to carry a paragraph explaining that nothing is
    written to disk, and the grid another about case law. Both true,
    both ignored: a block of prose that is always there becomes
    furniture, and the eye learns to skip it. The explanations live in
    the help page now, and this keeps them from creeping back.

    Modal dialogs are exempt: one appears because something is at stake,
    and it is read.
    """

    LIMIT = 90

    def setUp(self):
        self.source = GUI.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        # Read out of the source rather than imported: PySide6 is not
        # installed everywhere the suite runs, and this file is checked
        # precisely where it cannot be executed.
        self.help = _constant(self.tree, "HELP_TEXT")

    def _standing_texts(self):
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_label = isinstance(func, ast.Name) and func.id == "QLabel"
            is_set = (
                isinstance(func, ast.Attribute)
                and func.attr == "setText"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr.endswith(("_label", "_hint"))
            )
            if not (is_label or is_set):
                continue
            for argument in node.args:
                text = _joined(argument)
                if text:
                    yield text

    def test_no_standing_text_is_a_paragraph(self):
        for text in self._standing_texts():
            self.assertLessEqual(
                len(text), self.LIMIT,
                f"{len(text)} characters on screen: {text[:70]}...",
            )

    def test_the_help_page_exists_and_is_reachable(self):
        self.assertIn("HELP_TEXT", self.source)
        self.assertIn('QPushButton("Aide")', self.source)

    def test_the_help_covers_what_was_taken_off_the_screen(self):
        """Shortening the screen must not lose the warnings."""
        for subject in ("mémoire", "fermez", "image", "PDF", "jurisprudence",
                        "voyant", "refuse"):
            self.assertIn(subject.lower(), self.help.lower(), subject)

    def test_the_help_itself_is_scannable(self):
        """Headings and short paragraphs, not an essay."""
        headings = self.help.count("<h2>")
        self.assertGreaterEqual(headings, 6, "too few sections to scan")

        paragraphs = re.findall(r"<p>(.*?)</p>", self.help, re.S)
        self.assertTrue(paragraphs)
        for paragraph in paragraphs:
            self.assertLess(len(paragraph), 320, paragraph[:60])


def _constant(tree, name: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return _joined(node.value)
    raise AssertionError(f"{name} is missing from gui.py")


def _joined(node) -> str:
    """The text of a literal, including implicit concatenation."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "xxxxx"
            for part in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _joined(node.left) + _joined(node.right)
    return ""


class LeavingTheHelp(unittest.TestCase):
    """A page you cannot leave is worse than no page.

    The help button sits in the status bar and stays there while the
    help is open. Recording the current page on every click meant a
    second click recorded the help itself, and "Retour" then returned to
    the help: the user was stuck with no way out but closing the window,
    which loses the cycle.
    """

    def setUp(self):
        self.source = GUI.read_text(encoding="utf-8")

    def test_the_help_button_toggles(self):
        """A second click on the button that opened it must close it.

        That is the only thing it can sensibly do while it stays on
        screen, and it is what anyone tries first.
        """
        toggle = self.source[self.source.index("def _toggle_help"):]
        toggle = toggle[:toggle.index("def _close_help")]
        self.assertIn("== HELP", toggle, "the button does not close the help")
        self.assertIn("_close_help()", toggle)

    def test_escape_closes_the_help(self):
        self.assertIn("Key_Escape", self.source)

    def test_there_is_exactly_one_close_button_on_the_page(self):
        """Two of them was treating the symptom, not the problem."""
        self.assertEqual(
            self.source.count("clicked.connect(self._close_help)"), 1,
            "more than one close button on the help page",
        )

    def test_no_signal_is_wired_to_a_method_that_takes_arguments(self):
        """clicked passes checked=False to whatever accepts a parameter.

        "Effacer le cycle" was wired to _reset(confirm=True), so the click
        arrived as confirm=False and cleared the cycle without asking.
        Only running the window showed it; once known, the shape is easy
        to forbid. A lambda says which arguments are meant.
        """
        tree = ast.parse(self.source)
        methods = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connect" and node.args):
                continue
            target = node.args[0]
            if isinstance(target, ast.Attribute) and target.attr in methods:
                parameters = methods[target.attr].args.args[1:]
                self.assertEqual(
                    parameters, [],
                    f"line {node.lineno}: {target.attr} takes parameters a signal would fill",
                )


if __name__ == "__main__":
    unittest.main()
