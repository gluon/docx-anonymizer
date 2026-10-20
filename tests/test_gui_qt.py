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

HOME, GRID, RESULT, RETURN, HELP, DOSSIER, CASE_RESULTS = range(7)



class _NoNetwork:
    clean = True
    attempts = 0


def _dismiss(tries: int = 100) -> None:
    """Close whatever modal box comes up, whichever button it offers.

    Retried rather than fired once: a box is only there once ``exec``
    has started, and a handler that looks too early finds nothing and
    leaves the window blocked for good.
    """
    box = QApplication.activeModalWidget()
    if isinstance(box, QMessageBox) and box.buttons():
        box.buttons()[0].click()
        return
    if tries:
        QTimer.singleShot(20, lambda: _dismiss(tries - 1))


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
        # Let it close without asking. The window asks when names are
        # held and nothing is saved, and it reads that from the case, so
        # emptying the mapping alone is no longer enough: every test
        # would hang on a modal nobody answers.
        self.window.mapping = None
        self.window.case = self.gui.Case()
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
    def test_every_pseudonym_can_be_read(self):
        """The column the user must read before trusting the export.

        Asserting that the text fits was too rigid: it held on macOS and
        failed on Windows, where the default font is wider, for a
        pseudonym needing 348 pixels in a 273 pixel column. The
        requirement is that the text be readable, which a tooltip also
        satisfies, and which stays true on a font or a window size
        nobody has tried yet.
        """
        self.to_grid()
        metrics = self.window.table.fontMetrics()
        width = self.window.table.columnWidth(3)
        for index in range(self.window.table.rowCount()):
            item = self.window.table.item(index, 3)
            text = item.text()
            with self.subTest(pseudonym=text):
                fits = metrics.horizontalAdvance(text) + 12 <= width
                self.assertTrue(
                    fits or text in item.toolTip(),
                    f"{text!r} is cut off and its tooltip does not carry it",
                )

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

    def test_copier_says_it_copied(self):
        self.to_result()
        self.click("Copier")
        self.assertEqual(QApplication.clipboard().text(), self.window.result_area.toPlainText())
        self.button("Copié ✓")

    def test_text_areas_have_names(self):
        for area in (self.window.paste_area, self.window.return_area, self.window.result_area):
            self.assertTrue(area.accessibleName(), area)

    def test_the_why_column_can_be_read_in_full(self):
        self.to_grid()
        for index in range(self.window.table.rowCount()):
            item = self.window.table.item(index, 4)
            self.assertEqual(item.toolTip(), item.text())

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


    # ------------------------------------------------------------- dossier
    def _case_of_two(self, folder: Path):
        """A document and a pasted text, in one case, analysed."""
        from unittest import mock
        from PySide6.QtWidgets import QFileDialog
        import fixtures

        source = fixtures.build(folder / "Dossier_Dupont.docx")
        self.click("Un dossier, plusieurs pièces")
        self.assertEqual(self.at(), DOSSIER)
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(str(source), "")):
            self.click("Ajouter un document Word")
        self.click("Ajouter un texte collé")
        self.window.case_paste.insertPlainText(
            "Jean Dupont conteste. Son conseil est Maitre Sylvie Marchand."
        )
        self.click("Ajouter ce texte")
        self.assertEqual(self.window.pieces_table.rowCount(), 2)
        self.click("Analyser le dossier")
        self.assertEqual(self.at(), GRID)
        return source

    def test_a_case_walks_from_its_pieces_to_the_grid(self):
        import tempfile

        self._case_of_two(Path(tempfile.mkdtemp()))
        self.assertEqual(self.window.table.columnCount(), 6)
        self.assertEqual(
            self.window.table.horizontalHeaderItem(5).text(), "Pièces")
        self.assertGreater(self.window.table.rowCount(), 0)

    def test_one_document_keeps_the_five_column_grid(self):
        """The simple flow must not grow a column it has nothing to put in."""
        self.to_grid()
        self.assertEqual(self.window.table.columnCount(), 5)

    def test_the_same_person_carries_one_name_across_the_pieces(self):
        import tempfile

        self._case_of_two(Path(tempfile.mkdtemp()))
        rows = {row.value: row for row in self.window.grid.rows}
        self.assertEqual(rows["Jean Dupont"].group, rows["DUPONT"].group)
        self.assertEqual(
            rows["Jean Dupont"].pseudonym.split()[-1].upper(),
            rows["DUPONT"].pseudonym.upper(),
        )

    def test_a_case_writes_every_piece_into_the_chosen_folder(self):
        import tempfile
        from unittest import mock
        from PySide6.QtWidgets import QFileDialog

        folder = Path(tempfile.mkdtemp())
        out = Path(tempfile.mkdtemp())
        self._case_of_two(folder)
        with mock.patch.object(QFileDialog, "getExistingDirectory", return_value=str(out)):
            self.click("Produire les pièces anonymes")
        self.assertEqual(self.at(), CASE_RESULTS)
        self.assertEqual(self.window.case_results_table.rowCount(), 2)
        written = list(out.glob("*_ANON.docx"))
        self.assertEqual(len(written), 1, [p.name for p in out.iterdir()])
        self.assertNotIn("Dupont", written[0].name)

    def test_a_pasted_piece_is_copied_from_the_list(self):
        import tempfile
        from unittest import mock
        from PySide6.QtWidgets import QApplication as App, QFileDialog

        out = Path(tempfile.mkdtemp())
        self._case_of_two(Path(tempfile.mkdtemp()))
        with mock.patch.object(QFileDialog, "getExistingDirectory", return_value=str(out)):
            self.click("Produire les pièces anonymes")
        self.click("Copier")
        masked = App.clipboard().text()
        self.assertTrue(masked)
        self.assertNotIn("Dupont", masked)

    def test_restoring_one_piece_is_not_refused_for_the_others(self):
        """The case's table holds pseudonyms this piece never carried.

        Asked of the whole table, the check that a pseudonym has not
        been reworded refuses every piece for the names it never
        contained. This is that regression, driven through the window.
        """
        import tempfile
        from unittest import mock
        from PySide6.QtWidgets import QApplication as App, QFileDialog

        out = Path(tempfile.mkdtemp())
        self._case_of_two(Path(tempfile.mkdtemp()))
        with mock.patch.object(QFileDialog, "getExistingDirectory", return_value=str(out)):
            self.click("Produire les pièces anonymes")
        self.click("Copier")
        masked = App.clipboard().text()

        self.click("J'ai les réponses de l'IA, remettre les vrais noms")
        self.assertEqual(self.at(), RETURN)
        self.assertTrue(self.window.piece_row.isVisible())
        index = self.window.piece_choice.findText("Texte collé 1")
        self.assertGreater(index, 0)
        self.window.piece_choice.setCurrentIndex(index)
        self.window.return_area.setPlainText(masked)
        self.click("Remettre les vrais noms")
        self.assertEqual(self.at(), RESULT, self.seen_dialogs)
        self.assertIn("Jean Dupont", self.window.result_area.toPlainText())

    def test_the_piece_question_is_not_asked_of_a_single_document(self):
        self.to_result()
        self.click("J'ai la réponse de l'IA, remettre les vrais noms")
        self.assertFalse(self.window.piece_row.isVisible())

    def test_the_same_document_cannot_be_added_twice(self):
        import tempfile
        from unittest import mock
        from PySide6.QtWidgets import QFileDialog
        import fixtures

        folder = Path(tempfile.mkdtemp())
        source = fixtures.build(folder / "Dossier_Dupont.docx")
        self.click("Un dossier, plusieurs pièces")
        for attempt in range(2):
            if attempt:
                self.answer_next_dialog()
            with mock.patch.object(QFileDialog, "getOpenFileName",
                                   return_value=(str(source), "")):
                self.click("Ajouter un document Word")
        self.assertEqual(self.window.pieces_table.rowCount(), 1)
        self.assertTrue(any("déjà" in text for text in self.seen_dialogs),
                        self.seen_dialogs)

    def test_a_piece_can_be_removed(self):
        import tempfile

        self._case_of_two(Path(tempfile.mkdtemp()))
        self.click("Retour")
        self.click("Un dossier, plusieurs pièces")
        self.assertEqual(self.at(), DOSSIER)
        self.window.pieces_table.setCurrentCell(0, 0)
        self.click("Retirer la pièce choisie")
        self.assertEqual(self.window.pieces_table.rowCount(), 1)

    def test_a_saved_table_is_reopened_and_restores(self):
        import tempfile
        from unittest import mock
        from PySide6.QtWidgets import QApplication as App, QFileDialog

        out = Path(tempfile.mkdtemp())
        self._case_of_two(Path(tempfile.mkdtemp()))
        with mock.patch.object(QFileDialog, "getExistingDirectory", return_value=str(out)):
            self.click("Produire les pièces anonymes")
        self.click("Copier")
        masked = App.clipboard().text()

        table = out / f"dossier{self.gui.SUFFIX}"
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(table), "")):
            QTimer.singleShot(0, _dismiss)
            self.click("Enregistrer la table du dossier")
        self.assertTrue(table.exists())
        self.assertIn("ne doit pas être transmis", table.read_text(encoding="utf-8"))

        fresh = self.gui.Window(_NoNetwork())
        try:
            fresh.show()
            with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(str(table), "")):
                QTimer.singleShot(0, _dismiss)
                fresh._case_load()
            self.assertEqual(len(fresh.case.pieces), 2)
            outcome = fresh.case.restore_text(masked, label="Texte collé 1")
            self.assertTrue(outcome.ok, outcome.refused)
            self.assertIn("Jean Dupont", outcome.text)
        finally:
            fresh.case = self.gui.Case()
            fresh.close()
            fresh.deleteLater()

    def test_closing_a_saved_case_does_not_ask(self):
        """Saved, there is nothing left to lose by closing."""
        import tempfile
        from unittest import mock
        from PySide6.QtWidgets import QFileDialog

        out = Path(tempfile.mkdtemp())
        self._case_of_two(Path(tempfile.mkdtemp()))
        with mock.patch.object(QFileDialog, "getExistingDirectory", return_value=str(out)):
            self.click("Produire les pièces anonymes")
        table = out / f"dossier{self.gui.SUFFIX}"
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(table), "")):
            QTimer.singleShot(0, _dismiss)
            self.click("Enregistrer la table du dossier")
        self.assertTrue(self.window.close())


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
