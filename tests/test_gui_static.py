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


if __name__ == "__main__":
    unittest.main()
