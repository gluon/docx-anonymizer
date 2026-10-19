"""The window, actually run.

``test_gui_static`` reads gui.py without executing it, and a help page
that could not be left went straight through it. These tests build the
real window on Qt's offscreen platform and drive it with QTest: clicks
on the real buttons, the real stack, the real message boxes.

Skipped where PySide6 is not installed.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
except ImportError:  # pragma: no cover - environment without Qt
    QApplication = None

SAMPLE = Path(__file__).with_name("sample_mail.txt").read_text(encoding="utf-8")

HOME, GRID, RESULT, RETURN, HELP = range(5)



class _NoNetwork:
    clean = True
    attempts = 0


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dxanon import gui
        cls.gui = gui
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = self.gui.Window(_NoNetwork())
        self.window.show()
        self.window.activateWindow()
        QTest.qWaitForWindowActive(self.window)
        self.seen_dialogs: list[str] = []
        self.alive = True

    def tearDown(self):
        self.alive = False  # a handler still waiting must not answer the next test
        self.window.mapping = None  # let it close without asking
        self.window.close()
        self.window.deleteLater()

    # ------------------------------------------------------------ helpers
    def button(self, text: str) -> QPushButton:
        page = self.window.stack.currentWidget()
        for candidate in page.findChildren(QPushButton) + self.window.statusBar().findChildren(QPushButton):
            if candidate.text() == text and candidate.isVisible():
                return candidate
        self.fail(f"no visible button {text!r} on page {self.window.stack.currentIndex()}")

    def click(self, text: str) -> None:
        QTest.mouseClick(self.button(text), Qt.LeftButton)

    def answer_next_dialog(self, choice: str | None = None) -> None:
        """Close the next modal box, pressing the button labelled ``choice``.

        The box is recorded by its text, which now carries the title:
        macOS drops message box titles. The handler gives up after two
        seconds, so a box that never comes cannot leak into the next test
        and answer a dialog that belongs to it.
        """
        deadline = [100]

        def handle():
            if not self.alive:
                return
            box = QApplication.activeModalWidget()
            if not isinstance(box, QMessageBox):
                deadline[0] -= 1
                if deadline[0] > 0:
                    QTimer.singleShot(20, handle)
                return
            self.seen_dialogs.append(box.text())
            for candidate in box.buttons():
                if choice is None or candidate.text() == choice:
                    candidate.click()
                    return
            self.fail(f"no button {choice!r} in {box.text()!r}")
        QTimer.singleShot(0, handle)

    def at(self) -> int:
        return self.window.stack.currentIndex()

    def to_grid(self) -> None:
        self.click("Coller du texte")
        self.window.paste_area.insertPlainText(SAMPLE[:1500])  # a paste, not typing
        self.click("Analyser")
        self.assertEqual(self.at(), GRID)

    def to_result(self) -> None:
        self.to_grid()
        self.click("Produire la version anonyme")
        self.assertEqual(self.at(), RESULT)

    # --------------------------------------------------------- navigation
    def test_walks_through_the_four_screens_and_back(self):
        self.assertEqual(self.at(), HOME)
        self.to_grid()
        self.assertGreater(self.window.table.rowCount(), 0)
        self.click("Retour")
        self.assertEqual(self.at(), HOME)
        self.click("Analyser")
        self.assertEqual(self.at(), GRID)
        self.click("Produire la version anonyme")
        self.assertEqual(self.at(), RESULT)
        masked = self.window.result_area.toPlainText()
        self.assertNotIn("BENZAOUI", masked)
        self.click("J'ai la réponse de l'IA, remettre les vrais noms")
        self.assertEqual(self.at(), RETURN)
        self.window.return_area.setPlainText(masked)
        self.click("Remettre les vrais noms")
        self.assertEqual(self.at(), RESULT)
        self.assertEqual(self.window.result_area.toPlainText(), SAMPLE[:1500].strip())

    def test_resume_button_appears_only_during_a_cycle(self):
        self.assertFalse(self.window.resume_button.isVisible())
        self.to_result()
        self.window.stack.setCurrentIndex(HOME)
        self.assertTrue(self.window.resume_button.isVisible())
        self.click("Reprendre, et remettre les vrais noms")
        self.assertEqual(self.at(), RETURN)

    def test_the_return_screen_can_be_left(self):
        self.to_result()
        for origin, button in ((RESULT, "J'ai la réponse de l'IA, remettre les vrais noms"),
                               (HOME, "Reprendre, et remettre les vrais noms")):
            with self.subTest(origin=origin):
                self.window.stack.setCurrentIndex(origin)
                self.click(button)
                self.assertEqual(self.at(), RETURN)
                self.click("Retour")
                self.assertEqual(self.at(), origin)

    # ----------------------------------------------------------- keyboard
    def tab_from(self, widget):
        widget.setFocus()
        QTest.keyClick(widget, Qt.Key_Tab)
        return QApplication.focusWidget()

    def test_tab_leaves_the_paste_area_for_analyser(self):
        self.click("Coller du texte")
        self.assertIs(self.tab_from(self.window.paste_area), self.window.analyse_button)
        self.assertEqual(self.window.paste_area.toPlainText(), "")

    def test_tab_leaves_the_grid_for_produire(self):
        self.to_grid()
        self.assertEqual(self.tab_from(self.window.table).text(), "Produire la version anonyme")

    def test_tab_leaves_the_return_area_for_remettre(self):
        self.to_result()
        self.click("J'ai la réponse de l'IA, remettre les vrais noms")
        self.assertEqual(self.tab_from(self.window.return_area).text(), "Remettre les vrais noms")

    def test_each_screen_shows_one_main_button(self):
        expected = {HOME: "Analyser", GRID: "Produire la version anonyme",
                    RESULT: "J'ai la réponse de l'IA, remettre les vrais noms",
                    RETURN: "Remettre les vrais noms"}
        for screen, label in expected.items():
            page = self.window.stack.widget(screen)
            defaults = [b.text() for b in page.findChildren(QPushButton) if b.isDefault()]
            self.assertEqual(defaults, [label], screen)

    # --------------------------------------------------------------- help
    def test_help_opens_and_closes_from_every_screen(self):
        self.to_result()  # so that every screen has something to show
        for screen in (HOME, GRID, RESULT, RETURN):
            for closer in ("Fermer", "Fermer l'aide"):
                with self.subTest(screen=screen, closer=closer):
                    self.window.stack.setCurrentIndex(screen)
                    self.click("Aide")
                    self.assertEqual(self.at(), HELP)
                    self.click(closer)
                    self.assertEqual(self.at(), screen)

    def test_help_button_is_a_toggle(self):
        self.to_grid()
        self.click("Aide")
        self.assertEqual(self.at(), HELP)
        self.click("Fermer l'aide")
        self.assertEqual(self.at(), GRID)
        self.assertTrue(self.button("Aide").isVisible())

    def test_escape_closes_help(self):
        self.to_grid()
        self.click("Aide")
        QTest.keyClick(self.window, Qt.Key_Escape)
        self.assertEqual(self.at(), GRID)

    # --------------------------------------------------------------- grid
    def test_every_pseudonym_fits_its_column(self):
        """The column the user must read before trusting the export."""
        self.to_grid()
        metrics = self.window.table.fontMetrics()
        width = self.window.table.columnWidth(3)
        for index in range(self.window.table.rowCount()):
            text = self.window.table.item(index, 3).text()
            with self.subTest(pseudonym=text):
                self.assertLessEqual(metrics.horizontalAdvance(text) + 12, width)

    # ------------------------------------------------------------ refusal
    def test_export_refused_writes_nothing_and_stays_on_grid(self):
        self.to_grid()
        # Retype a pseudonym so that it still carries the real value.
        real = self.window.table.item(0, 1).text()
        self.window.table.item(0, 3).setText(real + " bis")
        self.answer_next_dialog()
        self.click("Produire la version anonyme")
        self.assertEqual(self.seen_dialogs, ["Export refusé, rien n'a été écrit"])
        self.assertEqual(self.at(), GRID)
        self.assertIsNone(self.window.mapping)
        self.assertEqual(self.window.result_area.toPlainText(), "")

    def test_produce_with_nothing_ticked_writes_nothing(self):
        """An empty table would hand back the original named _ANON."""
        self.to_grid()
        for row in self.window.grid.rows:
            row.decision = self.gui.Decision.KEEP
        self.window._fill_table()
        self.answer_next_dialog()
        self.click("Produire la version anonyme")
        self.assertEqual(self.seen_dialogs, ["Rien n'est coché, rien n'a été écrit"])
        self.assertEqual(self.at(), GRID)
        self.assertIsNone(self.window.mapping)

    def test_restore_with_nothing_pasted_says_so(self):
        self.to_result()
        self.click("J'ai la réponse de l'IA, remettre les vrais noms")
        self.answer_next_dialog()
        self.click("Remettre les vrais noms")
        self.assertEqual(self.seen_dialogs, ["Rien à restaurer"])
        self.assertEqual(self.at(), RETURN)

    def test_a_text_with_no_pseudonym_is_not_called_reworded(self):
        self.to_result()
        self.click("J'ai la réponse de l'IA, remettre les vrais noms")
        self.window.return_area.setPlainText("Un tout autre texte.")
        captured = []
        original = self.gui._alert
        self.gui._alert = lambda parent, icon, title, body: captured.append(body)
        try:
            self.click("Remettre les vrais noms")
        finally:
            self.gui._alert = original
        self.assertEqual(len(captured), 1)
        self.assertNotIn("reformulés", captured[0])
        self.assertIn("Aucun des pseudonymes", captured[0])

    def test_one_reworded_pseudonym_is_named(self):
        self.to_result()
        masked = self.window.result_area.toPlainText()
        entry = next(e for e in self.window.mapping.entries
                     if self.window.mapping.was_used(e) and e.pseudonym in masked)
        self.click("J'ai la réponse de l'IA, remettre les vrais noms")
        self.window.return_area.setPlainText(masked.replace(entry.pseudonym, "Quelqu'un"))
        captured = []
        original = self.gui._alert
        self.gui._alert = lambda parent, icon, title, body: captured.append(body)
        try:
            self.click("Remettre les vrais noms")
        finally:
            self.gui._alert = original
        self.assertIn("reformulés", captured[0])
        self.assertIn(entry.pseudonym, captured[0])

    def test_restore_of_an_unrelated_text_is_refused(self):
        self.to_result()
        self.click("J'ai la réponse de l'IA, remettre les vrais noms")
        self.window.return_area.setPlainText("Rien de ce qui a été envoyé.")
        self.answer_next_dialog()
        self.click("Remettre les vrais noms")
        self.assertEqual(self.seen_dialogs, ["Restauration refusée, rien n'a été écrit"])
        self.assertEqual(self.at(), RETURN)

    def test_analyser_on_an_empty_area_says_so(self):
        self.click("Coller du texte")
        self.answer_next_dialog()
        self.click("Analyser")
        self.assertEqual(self.seen_dialogs, ["Rien à analyser"])
        self.assertEqual(self.at(), HOME)

    def test_after_a_restoration_the_buttons_say_what_is_left(self):
        self.to_result()
        masked = self.window.result_area.toPlainText()
        self.click("J'ai la réponse de l'IA, remettre les vrais noms")
        self.window.return_area.setPlainText(masked)
        self.click("Remettre les vrais noms")
        self.assertEqual(self.at(), RESULT)
        self.button("Restaurer une autre réponse")
        self.button("Terminer, effacer le cycle")
        self.click("Restaurer une autre réponse")
        self.assertEqual(self.at(), RETURN)

    # --------------------------------------------------------------- docx
    def test_with_a_file_the_result_opens_its_folder(self):
        import tempfile
        from unittest import mock
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QFileDialog
        import fixtures

        folder = Path(tempfile.mkdtemp())
        source = fixtures.build(folder / "Dossier_Dupont.docx")
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(str(source), "")):
            self.click("Ouvrir un document Word")
        self.click("Produire la version anonyme")
        with mock.patch.object(QDesktopServices, "openUrl") as opened:
            self.click("Ouvrir le dossier")
        self.assertEqual(Path(opened.call_args[0][0].toLocalFile()), folder)

    def test_docx_export_through_the_window_keeps_the_name_out(self):
        import tempfile
        import zipfile
        from unittest import mock
        from PySide6.QtWidgets import QFileDialog
        import fixtures

        folder = Path(tempfile.mkdtemp())
        source = fixtures.build(folder / "Dossier_Dupont.docx")
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(str(source), "")):
            self.click("Ouvrir un document Word")
        self.assertEqual(self.at(), GRID)
        self.click("Produire la version anonyme")
        self.assertEqual(self.at(), RESULT)

        written = [p for p in folder.iterdir() if p.name.endswith("_ANON.docx")]
        self.assertEqual(len(written), 1)
        self.assertNotIn("Dupont", written[0].name)
        with zipfile.ZipFile(written[0]) as archive:
            blob = b"".join(archive.read(n) for n in archive.namelist())
        for real in fixtures.PLANTED:
            self.assertNotIn(real.encode(), blob)

    def test_an_existing_file_is_never_overwritten(self):
        """The _ANON file there may be the one just back from the AI."""
        import tempfile
        from unittest import mock
        from PySide6.QtWidgets import QFileDialog
        import fixtures

        folder = Path(tempfile.mkdtemp())
        source = fixtures.build(folder / "Dossier_Dupont.docx")
        for _ in range(2):
            self.window._reset(confirm=False)
            with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(str(source), "")):
                self.click("Ouvrir un document Word")
            first = sorted(folder.glob("*_ANON*.docx"))
            if first:
                first[0].write_bytes(b"revenu de l'IA")
            self.click("Produire la version anonyme")
        written = sorted(p.name for p in folder.glob("*_ANON*.docx"))
        self.assertEqual(len(written), 2, written)
        self.assertEqual((folder / written[0]).read_bytes(), b"revenu de l'IA")
        self.assertIn(written[1], self.window.result_area.toPlainText())

    def test_docx_comes_back_untouched_and_is_restored(self):
        """The return trip used to demand pseudonyms that never fired."""
        import tempfile
        from unittest import mock
        from PySide6.QtWidgets import QFileDialog
        import fixtures

        folder = Path(tempfile.mkdtemp())
        source = fixtures.build(folder / "Dossier_Dupont.docx")
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(str(source), "")):
            self.click("Ouvrir un document Word")
        self.click("Produire la version anonyme")
        written = next(p for p in folder.iterdir() if p.name.endswith("_ANON.docx"))
        self.click("J'ai la réponse de l'IA, remettre les vrais noms")
        self.answer_next_dialog()
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(str(written), "")):
            self.click("Ouvrir un document corrigé")
        self.assertEqual(self.seen_dialogs, [])
        self.assertTrue((folder / "Dossier_Dupont_FINAL.docx").exists(),
                        sorted(p.name for p in folder.iterdir()))

    # -------------------------------------------------------------- close
    def test_starting_over_during_a_cycle_asks_first(self):
        self.to_result()
        held = self.window.mapping
        self.window.stack.setCurrentIndex(HOME)
        self.answer_next_dialog("Revenir")
        self.click("Analyser")
        self.assertEqual(self.seen_dialogs, ["Un cycle est en cours"])
        self.assertIs(self.window.mapping, held)
        self.assertEqual(self.at(), HOME)

        self.answer_next_dialog("Revenir")
        self.click("Ouvrir un document Word")  # no file dialog may open
        self.assertIs(self.window.mapping, held)

        self.answer_next_dialog("Abandonner le cycle")
        self.click("Analyser")
        self.assertIsNone(self.window.mapping)
        self.assertEqual(self.at(), GRID)

    def test_close_without_cycle_does_not_ask(self):
        self.window.close()
        self.assertFalse(self.window.isVisible())
        self.assertEqual(self.seen_dialogs, [])

    def test_close_during_cycle_asks_and_can_be_cancelled(self):
        self.to_result()
        self.answer_next_dialog("Revenir")
        self.window.close()
        self.assertEqual(self.seen_dialogs, ["Un cycle est en cours"])
        self.assertTrue(self.window.isVisible())
        self.assertIsNotNone(self.window.mapping)

    def test_close_during_cycle_can_be_forced(self):
        self.to_result()
        self.answer_next_dialog("Fermer quand même")
        self.window.close()
        self.assertFalse(self.window.isVisible())

    def test_clear_cycle_asks_then_returns_home(self):
        self.to_result()
        self.answer_next_dialog("Annuler")
        self.click("Effacer le cycle")
        self.assertEqual(self.seen_dialogs, ["Effacer le cycle ?"])
        self.assertIsNotNone(self.window.mapping)
        self.answer_next_dialog("Effacer")
        self.click("Effacer le cycle")
        self.assertIsNone(self.window.mapping)
        self.assertEqual(self.at(), HOME)


class StartupTypeCheck(unittest.TestCase):
    """The lazy creation seen in the macOS crash trace happens at import.

    Run in a fresh interpreter: in this one other tests have long since
    touched QCloseEvent, which would make the check pass for free.
    """

    @unittest.skipIf(QApplication is None, "PySide6 not installed")
    def test_close_event_type_exists_before_any_window_closes(self):
        import subprocess
        probe = (
            "import PySide6.QtGui as g\n"
            "assert 'QCloseEvent' not in g.__dict__, 'already created'\n"
            "import dxanon.gui\n"
            "assert type(g.__dict__['QCloseEvent']).__name__ == 'ObjectType'\n"
            "dxanon.gui._check_event_types()\n"
            "print('ok')\n"
        )
        src = str(Path(__file__).resolve().parents[1] / "src")
        env = dict(os.environ, PYTHONPATH=src)
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                                text=True, env=env, timeout=60)
        self.assertEqual(result.stdout.strip(), "ok", result.stderr)


if __name__ == "__main__":
    unittest.main()
