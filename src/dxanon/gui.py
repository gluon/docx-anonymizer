"""The window.

Deliberately thin. Every decision it shows comes from :mod:`workflow`,
every substitution from :mod:`engine` or :mod:`plaintext`, and both are
covered by tests that need no display. What lives here is layout and
wiring. tests/test_gui_qt.py builds this window on Qt's offscreen
platform and drives it with clicks; it has also been run by hand on
macOS. It has not been run on Windows.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6 import QtGui
from PySide6.QtCore import QEvent, Qt, QUrl
# QCloseEvent is imported for its side effect as much as for the type hint.
# PySide creates a wrapper type lazily, the first time Python touches it.
# For QCloseEvent that first time used to be inside closeEvent, while macOS
# was terminating the application, and a crash report shows a segfault in
# exactly that lazy initialisation. Naming the type here creates it when
# the module loads. _check_event_types proves it did.
from PySide6.QtGui import QCloseEvent, QDesktopServices, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout,
    QWidget,
)

from . import engine, plaintext, source, workflow
from .detect import Certainty
from .engine import EmptyTable, RefusedExport
from .mapping import Mapping
from .netguard import NetworkGuard
from .workflow import Decision

#: Index of the help page in the stack, so the other screens stay 0..3.
HELP = 4

HELP_TEXT = """
<style>
  h2 { margin-bottom: 2px; }
  p, li { margin-top: 2px; margin-bottom: 6px; }
</style>

<h2>Le principe</h2>
<p>Vous masquez les noms, vous travaillez avec l'IA sur la version
masquée, vous remettez les vrais noms au retour. L'original ne sort
jamais de cet ordinateur.</p>

<h2>Le cycle</h2>
<ol>
  <li>Collez un texte, ou ouvrez un document Word.</li>
  <li>Vérifiez la grille, décochez ce qui ne doit pas être masqué.</li>
  <li>Copiez la version masquée dans le chat, travaillez.</li>
  <li>Revenez, collez la réponse, récupérez vos vrais noms.</li>
</ol>

<h2>Ne fermez pas la fenêtre en cours de cycle</h2>
<p>La correspondance entre vrais noms et pseudonymes n'est enregistrée
nulle part : elle n'existe qu'en mémoire, le temps de l'aller-retour.
C'est voulu, car ce fichier serait le plus dangereux du dossier.</p>
<p>Conséquence : si vous fermez la fenêtre avant d'avoir remis les vrais
noms, ils sont perdus, et tout document déjà masqué devient illisible.
La fenêtre vous prévient avant de se fermer.</p>

<h2>Les trois niveaux de la grille</h2>
<p><b>Certain</b> : numéro de sécurité sociale, IBAN, SIRET, adresse,
email, téléphone. Reconnus à leur forme, masqués d'office.</p>
<p><b>À confirmer</b> : tout ce qui ressemble à un nom propre. L'outil
propose, vous tranchez. Il propose large : mieux vaut décocher un mot
de trop que laisser passer un nom.</p>
<p><b>Jurisprudence</b> : les noms de parties dans un arrêt cité sont
<b>conservés</b>. Ce sont des noms publics, et les masquer rendrait la
citation incompréhensible.</p>

<h2>Ce que l'outil ne sait pas faire</h2>
<ul>
  <li><b>Lire le texte dans les images.</b> Signature scannée, tampon,
      capture d'écran : il les signale, à vous de décider.</li>
  <li><b>Les PDF.</b> Documents Word et texte collé uniquement.</li>
  <li><b>Juger ce qui est sensible.</b> Il applique ce que vous cochez.</li>
  <li><b>Un nom jamais écrit avec une majuscule</b> nulle part dans le
      document.</li>
</ul>

<h2>Masquer les noms ne suffit pas toujours</h2>
<p>Une entreprise de douze personnes dans une commune nommée reste
reconnaissable même sans aucun nom. Cet arbitrage reste le vôtre.</p>

<h2>Le voyant en bas à droite</h2>
<p>Vert tant qu'aucune connexion réseau n'a été ouverte. Le programme
bloque ses propres connexions et compte les tentatives : vous pouvez le
constater plutôt que nous croire.</p>

<h2>Si l'outil refuse de produire un fichier</h2>
<p>C'est qu'il a retrouvé une valeur réelle dans ce qu'il allait écrire.
Il n'écrit rien et vous dit laquelle. De même au retour, s'il ne
retrouve pas tous les pseudonymes : l'IA en a reformulé un, et il
préfère refuser plutôt que de rendre un document à moitié restauré.</p>
"""

CERTAINTY_LABEL = {
    Certainty.CERTAIN: "Certain",
    Certainty.CONFIRM: "À confirmer",
    Certainty.CASE_LAW: "Jurisprudence",
}


class Window(QMainWindow):
    def __init__(self, guard: NetworkGuard) -> None:
        super().__init__()
        _check_event_types()
        self.guard = guard
        self.grid: workflow.Grid | None = None
        self.source_text = ""
        self.source_file: Path | None = None
        self.workspace = Path.home() / "Documents"

        #: The correspondence table, held in memory and nowhere else.
        #: Writing it to disk would put the one file that maps every
        #: pseudonym back to the client on the firm's disk, and would
        #: then need a delete button to remove what should never have
        #: been written. Closing the window loses the cycle, which is
        #: said on screen rather than discovered.
        self.mapping: Mapping | None = None
        #: The screen the return page goes back to.
        self._return_from = 0
        #: The file the result screen shows, when it shows one.
        self.result_file: Path | None = None

        self.setWindowTitle("Anonymiseur de documents")
        self.resize(1100, 740)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.stack.addWidget(self._build_home())
        self.stack.addWidget(self._build_grid())
        self.stack.addWidget(self._build_result())
        self.stack.addWidget(self._build_return())
        self.stack.addWidget(self._build_help())

        self._build_status_bar()

    # ------------------------------------------------------------- chrome
    def _build_status_bar(self) -> None:
        self.help_button = QPushButton("Aide")
        self.help_button.setFlat(True)
        self.help_button.clicked.connect(self._toggle_help)
        self.statusBar().addWidget(self.help_button)

        self.network_label = QLabel()
        self.network_label.setContentsMargins(8, 0, 8, 0)
        self.statusBar().addPermanentWidget(self.network_label)
        self._refresh_network_label()

    def _toggle_help(self) -> None:
        """One button, one behaviour: it opens the help and it closes it.

        The button stays in the status bar while the help is open, so
        the only thing a second click can sensibly do is go back. An
        earlier version recorded the current page on every click, which
        recorded the help itself and left no way out; the fix was two
        close buttons, which was treating the symptom.
        """
        if self.stack.currentIndex() == HELP:
            self._close_help()
            return
        self._came_from = self.stack.currentIndex()
        self.stack.setCurrentIndex(HELP)
        self.help_button.setText("Fermer l'aide")

    def _close_help(self) -> None:
        self.stack.setCurrentIndex(getattr(self, "_came_from", 0))
        self.help_button.setText("Aide")

    # --------------------------------------------------------------- help
    def _build_help(self) -> QWidget:
        """Everything that used to sit on screen being ignored.

        The home page carried a paragraph explaining that nothing is
        written to disk, and the grid carried another about case law.
        Both were true, both were read by nobody: a standing wall of
        text is furniture, and the eye learns to skip it. It belongs
        behind a button, written to be scanned rather than read.
        """
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(28, 24, 28, 24)

        header = QHBoxLayout()
        title = QLabel("Aide")
        title.setFont(QFont(self.font().family(), 17, QFont.Bold))
        close_top = QPushButton("Fermer")
        close_top.clicked.connect(self._close_help)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close_top)
        outer.addLayout(header)

        body = QTextBrowser()
        body.setOpenExternalLinks(False)
        body.setHtml(HELP_TEXT)
        outer.addWidget(body, stretch=1)

        # A shortcut rather than a keyPressEvent override, which would bring
        # back the lazy event-type creation that _check_event_types rules
        # out, this time for QKeyEvent. Window-wide, because after a click
        # on "Aide" the focus stays on that button in the status bar,
        # outside the page; a shortcut on a hidden page is inactive, so it
        # only fires while the help is shown.
        escape = QShortcut(QKeySequence(Qt.Key_Escape), page)
        escape.setContext(Qt.WindowShortcut)
        escape.activated.connect(self._close_help)

        return page

    def _refresh_network_label(self) -> None:
        if self.guard.clean:
            self.network_label.setText("Hors ligne — aucune connexion ouverte")
            self.network_label.setStyleSheet("color: #146c43; font-weight: 600;")
        else:
            self.network_label.setText(
                f"{self.guard.attempts} connexion(s) bloquée(s)"
            )
            self.network_label.setStyleSheet("color: #b02a37; font-weight: 700;")

    # --------------------------------------------------------------- home
    def _build_home(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 36, 40, 36)
        layout.setSpacing(18)

        title = QLabel("Anonymiseur de documents")
        title.setFont(QFont(self.font().family(), 20, QFont.Bold))
        layout.addWidget(title)
        layout.addWidget(QLabel(
            "Masquez les noms avant de soumettre un texte à une IA, remettez-les au retour."
        ))

        buttons = QHBoxLayout()
        paste = QPushButton("Coller du texte")
        paste.clicked.connect(self._start_text)
        open_file = QPushButton("Ouvrir un document Word")
        open_file.clicked.connect(self._start_file)
        for button in (paste, open_file):
            button.setMinimumHeight(44)
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.cycle_label = QLabel()
        self.cycle_label.setWordWrap(True)
        layout.addWidget(self.cycle_label)

        self.resume_button = QPushButton("Reprendre, et remettre les vrais noms")
        self.resume_button.clicked.connect(self._open_return)
        layout.addWidget(self.resume_button)

        self.paste_area = QPlainTextEdit()
        # Tab leaves the area instead of typing a tab: otherwise the
        # keyboard can never reach the button under it.
        self.paste_area.setTabChangesFocus(True)
        self.paste_area.setPlaceholderText("Collez ici le texte à anonymiser…")
        self.paste_area.setVisible(False)
        layout.addWidget(self.paste_area, stretch=1)

        self.analyse_button = QPushButton("Analyser")
        self.analyse_button.setDefault(True)
        self.analyse_button.setVisible(False)
        self.analyse_button.clicked.connect(self._analyse_text)
        layout.addWidget(self.analyse_button)

        layout.addStretch()
        self._refresh_cycle()
        return page

    def _refresh_cycle(self) -> None:
        """Say what is held right now, and what closing the window costs.

        The table lives in memory only. That is the safer design, but it
        has a consequence the user must not discover by losing an hour of
        work: close this window and the real names of the current cycle
        are gone for good.
        """
        if self.mapping is None:
            self.cycle_label.setText("")
            self.resume_button.setVisible(False)
            return

        self.cycle_label.setText(
            f"Cycle en cours, {len(self.mapping.entries)} noms en mémoire. "
            "Ne fermez pas la fenêtre."
        )
        self.cycle_label.setStyleSheet("color: #d08700; font-weight: 600;")
        self.resume_button.setVisible(True)

    def _start_text(self) -> None:
        self.paste_area.setVisible(True)
        self.analyse_button.setVisible(True)
        self.paste_area.setFocus()

    def _may_start_over(self) -> bool:
        """Ask before a new analysis replaces the table of a cycle in progress.

        Opening another document used to drop the current table without a
        word: the same loss as closing the window, which asks. So this asks
        the same question, with "Revenir" as the default.
        """
        if self.mapping is None or not self.mapping.entries:
            return True
        question = QMessageBox(self)
        question.setWindowTitle("Un cycle est en cours")
        question.setIcon(QMessageBox.Warning)
        question.setText("Un cycle est en cours")
        question.setInformativeText(
            f"{len(self.mapping.entries)} correspondance(s) sont en mémoire et "
            "ne sont enregistrées nulle part.\n\n"
            "Si vous commencez un nouveau document, les vrais noms du cycle en "
            "cours seront définitivement perdus et tout document déjà anonymisé "
            "deviendra illisible."
        )
        question.setStandardButtons(QMessageBox.Cancel | QMessageBox.Discard)
        question.setDefaultButton(QMessageBox.Cancel)
        question.button(QMessageBox.Discard).setText("Abandonner le cycle")
        question.button(QMessageBox.Cancel).setText("Revenir")
        if question.exec() != QMessageBox.Discard:
            return False
        self.mapping = None
        self._refresh_cycle()
        return True

    def _start_file(self) -> None:
        if not self._may_start_over():
            return
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choisir un document Word", str(self.workspace), "Documents Word (*.docx)"
        )
        if not chosen:
            return
        self.source_file = Path(chosen)
        self.workspace = self.source_file.parent
        try:
            text, images, identities = source.read_document(self.source_file)
        except Exception as error:  # noqa: BLE001 - shown to the user as is
            _alert(self, QMessageBox.Critical, "Lecture impossible", str(error))
            return
        self.source_text = text
        self._open_grid(self.source_file.stem, images=images, known=identities)

    def _analyse_text(self) -> None:
        text = self.paste_area.toPlainText().strip()
        if not text:
            _alert(self, QMessageBox.Information, "Rien à analyser",
                   "La zone est vide. Collez-y le texte à anonymiser.")
            return
        if not self._may_start_over():
            return
        self.source_text = text
        self.source_file = None
        self._open_grid("Texte collé")

    # --------------------------------------------------------------- grid
    def _build_grid(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        self.grid_heading = QLabel()
        self.grid_heading.setFont(QFont(self.font().family(), 15, QFont.Bold))
        layout.addWidget(self.grid_heading)

        self.grid_hint = QLabel("Décochez ce qui ne doit pas être masqué.")
        self.grid_hint.setWordWrap(True)
        layout.addWidget(self.grid_hint)

        self.table = QTableWidget(0, 5)
        # Tab leaves the table; the arrows still move between cells.
        self.table.setTabKeyNavigation(False)
        self.table.setHorizontalHeaderLabels(
            ["Masquer", "Valeur trouvée", "Occurrences", "Remplacée par", "Pourquoi"]
        )
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        # The pseudonym is what the user reads and retypes before trusting
        # the export, so it gets as much room as the value it replaces.
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.table, stretch=1)

        self.images_label = QLabel()
        self.images_label.setWordWrap(True)
        self.images_label.setStyleSheet("color: #8a6d00; font-weight: 600;")
        layout.addWidget(self.images_label)

        row = QHBoxLayout()
        back = QPushButton("Retour")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        run = QPushButton("Produire la version anonyme")
        run.setMinimumHeight(40)
        run.clicked.connect(self._run)
        run.setDefault(True)
        row.addWidget(back)
        row.addStretch()
        row.addWidget(run)
        layout.addLayout(row)
        QWidget.setTabOrder(self.table, run)
        QWidget.setTabOrder(run, back)
        return page

    def _open_grid(self, label: str, images: list[str] | None = None,
                   known: list[str] | None = None) -> None:
        self.grid = workflow.build(self.source_text, images=images, known=known)
        self.grid_heading.setText(f"{len(self.grid.rows)} élément(s) repéré(s) — {label}")
        self._fill_table()
        self.images_label.setText(
            "" if not self.grid.images else
            f"{len(self.grid.images)} image(s) non traitée(s) : le texte qu'elles "
            "contiennent n'est pas lu."
        )
        self.stack.setCurrentIndex(1)

    def _fill_table(self) -> None:
        assert self.grid is not None
        self.table.setRowCount(len(self.grid.rows))
        for index, row in enumerate(self.grid.rows):
            box = QCheckBox()
            box.setChecked(row.decision is Decision.REPLACE)
            box.stateChanged.connect(lambda state, r=row: self._toggle(r, state))
            holder = QWidget()
            inner = QHBoxLayout(holder)
            inner.addWidget(box)
            inner.setAlignment(Qt.AlignCenter)
            inner.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(index, 0, holder)

            self.table.setItem(index, 1, _cell(row.value))
            self.table.setItem(index, 2, _cell(str(row.occurrences)))
            self.table.setItem(index, 3, QTableWidgetItem(row.pseudonym))
            self.table.setItem(index, 4, _cell(f"{CERTAINTY_LABEL[row.certainty]} — {row.why}"))

    def _toggle(self, row: workflow.Row, state: int) -> None:
        row.decision = Decision.REPLACE if state else Decision.KEEP

    def _collect_edits(self) -> None:
        """Take back any pseudonym the user retyped in the table."""
        assert self.grid is not None
        for index, row in enumerate(self.grid.rows):
            item = self.table.item(index, 3)
            if item is not None:
                row.pseudonym = item.text().strip()

    # ------------------------------------------------------------- result
    def _build_result(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)

        self.result_heading = QLabel()
        self.result_heading.setFont(QFont(self.font().family(), 15, QFont.Bold))
        layout.addWidget(self.result_heading)

        self.result_area = QPlainTextEdit()
        self.result_area.setReadOnly(True)
        self.result_area.setTabChangesFocus(True)
        layout.addWidget(self.result_area, stretch=1)

        row = QHBoxLayout()
        self.copy_button = copy = QPushButton("Copier")
        copy.clicked.connect(self._copy_result)
        self.restart_button = restart = QPushButton("Effacer le cycle")
        # Not connect(self._reset): clicked passes checked=False, which
        # landed in ``confirm`` and cleared the cycle without asking.
        restart.clicked.connect(lambda: self._reset())
        self.done_button = done = QPushButton("J'ai la réponse de l'IA, remettre les vrais noms")
        done.setMinimumHeight(40)
        done.clicked.connect(self._open_return)
        done.setDefault(True)
        row.addWidget(copy)
        row.addWidget(restart)
        row.addStretch()
        row.addWidget(done)
        layout.addLayout(row)
        return page

    def _show_result(self, heading: str, text: str = "", written: Path | None = None,
                     restored: bool = False) -> None:
        """One screen, two moments: after masking, and after restoring.

        After a restoration it kept offering "J'ai la réponse de l'IA" and
        "Effacer le cycle" as if nothing had happened. And with a file,
        "Copier" put the sentence "Fichier écrit : /chemin…" on the
        clipboard, which nobody can use: the button opens the folder then.
        """
        self.result_file = written
        self.result_heading.setText(heading)
        self.result_area.setPlainText(f"Fichier écrit :\n{written}" if written else text)
        self.copy_button.setText("Ouvrir le dossier" if written else "Copier")
        if restored:
            self.done_button.setText("Restaurer une autre réponse")
            self.restart_button.setText("Terminer, effacer le cycle")
        else:
            self.done_button.setText("J'ai la réponse de l'IA, remettre les vrais noms")
            self.restart_button.setText("Effacer le cycle")
        self.stack.setCurrentIndex(2)

    def _copy_result(self) -> None:
        if self.result_file is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result_file.parent)))
            return
        QApplication.clipboard().setText(self.result_area.toPlainText())

    def _run(self) -> None:
        assert self.grid is not None
        self._collect_edits()

        conflicts = self.grid.conflicts()
        if conflicts:
            _alert(self, QMessageBox.Warning, "Table incohérente", "\n".join(conflicts))
            return

        mapping = self.grid.to_mapping()
        try:
            if self.source_file is not None:
                destination = _unused(self.source_file.with_name(
                    f"{_masked_stem(self.source_file.stem, mapping)}_ANON.docx"))
                engine.anonymize(self.source_file, destination, mapping)
                shown, written = "", destination
            else:
                shown, written = plaintext.anonymize(self.source_text, mapping), None
        except EmptyTable:
            _alert(
                self, QMessageBox.Warning,
                "Rien n'est coché, rien n'a été écrit",
                "Sans aucune valeur à masquer, la « version anonyme » serait "
                "l'original sous un autre nom. Cochez au moins une ligne de la grille.",
            )
            return
        except RefusedExport as refused:
            _alert(
                self, QMessageBox.Critical,
                "Export refusé, rien n'a été écrit",
                "Des valeurs réelles subsistent :\n\n"
                + "\n".join(f"• {r.value} ({r.where})" for r in refused.residues[:12]),
            )
            return

        self.mapping = mapping
        self._refresh_cycle()
        self._refresh_network_label()
        self._show_result("Version anonyme — à soumettre à l'IA", shown, written)

    # ------------------------------------------------------------- return
    def _build_return(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)

        heading = QLabel("Remettre les vrais noms")
        heading.setFont(QFont(self.font().family(), 15, QFont.Bold))
        layout.addWidget(heading)
        layout.addWidget(QLabel("Collez le texte corrigé, ou ouvrez le document corrigé."))

        self.return_area = QPlainTextEdit()
        self.return_area.setTabChangesFocus(True)
        layout.addWidget(self.return_area, stretch=1)

        self.allow_partial = QCheckBox("Ce n'est qu'un extrait du texte masqué")
        layout.addWidget(self.allow_partial)

        row = QHBoxLayout()
        # The only screen without a way back: reached by mistake, it could
        # be left only by starting a restoration or through the help.
        back = QPushButton("Retour")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(self._return_from))
        open_file = QPushButton("Ouvrir un document corrigé")
        open_file.clicked.connect(self._restore_file)
        restore = QPushButton("Remettre les vrais noms")
        restore.setMinimumHeight(40)
        restore.clicked.connect(self._restore_text)
        restore.setDefault(True)
        row.addWidget(back)
        row.addWidget(open_file)
        row.addStretch()
        row.addWidget(restore)
        layout.addLayout(row)
        QWidget.setTabOrder(self.return_area, restore)
        QWidget.setTabOrder(restore, open_file)
        QWidget.setTabOrder(open_file, self.allow_partial)
        QWidget.setTabOrder(self.allow_partial, back)
        return page

    def _open_return(self) -> None:
        self._return_from = self.stack.currentIndex()
        self.stack.setCurrentIndex(3)

    def _mapping(self) -> Mapping | None:
        if self.mapping is None:
            _alert(
                self, QMessageBox.Warning,
                "Aucun cycle en cours",
                "Il n'y a pas de correspondance en mémoire. Rien n'étant "
                "enregistré sur le disque, un cycle commencé avant la "
                "fermeture de la fenêtre ne peut pas être repris : il faut "
                "repartir du document d'origine.",
            )
            return None
        return self.mapping

    def _restore_text(self) -> None:
        mapping = self._mapping()
        if mapping is None:
            return
        if not self.return_area.toPlainText().strip():
            _alert(
                self, QMessageBox.Information, "Rien à restaurer",
                "La zone est vide. Collez le texte renvoyé par l'IA, "
                "ou ouvrez le document corrigé.",
            )
            return
        try:
            restored, missing = plaintext.deanonymize(
                self.return_area.toPlainText(), mapping,
                require_all=not self.allow_partial.isChecked(),
            )
        except RefusedExport as refused:
            self._explain_refusal(refused, mapping)
            return
        self._show_result("Texte restauré", restored, restored=True)
        if missing:
            _alert(
                self, QMessageBox.Information, "Restauration partielle",
                "Non restaurés :\n" + "\n".join(f"• {v}" for v in missing[:12]),
            )

    def _restore_file(self) -> None:
        mapping = self._mapping()
        if mapping is None:
            return
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Document corrigé", str(self.workspace), "Documents Word (*.docx)"
        )
        if not chosen:
            return
        source = Path(chosen)
        stem = _restored_stem(source.stem.replace("_ANON", ""), mapping)
        destination = _unused(source.with_name(f"{stem}_FINAL.docx"))
        try:
            engine.deanonymize(source, destination, mapping,
                               require_all=not self.allow_partial.isChecked())
        except RefusedExport as refused:
            self._explain_refusal(refused, mapping)
            return
        self._show_result("Document restauré", written=destination, restored=True)

    def _explain_refusal(self, refused: RefusedExport, mapping: Mapping) -> None:
        expected = [e for e in mapping.entries if e.pseudonym and mapping.was_used(e)]
        if len(refused.residues) >= len(expected):
            # Not one pseudonym came back: the AI did not reword them all,
            # this is another text. Saying "reworded" sent the user looking
            # for a problem that was not there.
            _alert(
                self, QMessageBox.Warning,
                "Restauration refusée, rien n'a été écrit",
                "Aucun des pseudonymes de ce cycle n'apparaît dans ce texte. "
                "Ce n'est sans doute pas la version masquée produite par ce "
                "cycle, ni la réponse de l'IA à son sujet.",
            )
            return
        _alert(
            self, QMessageBox.Critical,
            "Restauration refusée, rien n'a été écrit",
            "Ces pseudonymes n'ont pas été retrouvés dans le texte renvoyé. "
            "L'IA les a probablement reformulés, et ils ne peuvent donc plus être "
            "remplacés par les vrais noms :\n\n"
            + "\n".join(f"• {r.value}" for r in refused.residues[:12])
            + "\n\nCorrigez-les dans le texte, ou cochez la case « extrait ».",
        )

    # -------------------------------------------------------------- reset
    def _reset(self, confirm: bool = True) -> None:
        """Clear the cycle. There is nothing on disk to clear with it.

        Forgetting the table is the whole operation, because the table
        was never written anywhere. That is also why it is worth a
        confirmation: once dropped, a document already masked can never
        be turned back.
        """
        if confirm and self.mapping is not None and self.mapping.entries:
            question = QMessageBox(self)
            question.setWindowTitle("Effacer le cycle")
            question.setIcon(QMessageBox.Warning)
            question.setText("Effacer le cycle ?")
            question.setInformativeText(
                f"Les {len(self.mapping.entries)} correspondance(s) en mémoire seront effacées. "
                "Les vrais noms de ce cycle ne pourront plus être remis. "
                "Tout document déjà anonymisé deviendra définitivement illisible."
            )
            question.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
            question.setDefaultButton(QMessageBox.Cancel)
            question.button(QMessageBox.Yes).setText("Effacer")
            question.button(QMessageBox.Cancel).setText("Annuler")
            if question.exec() != QMessageBox.Yes:
                return

        self.mapping = None
        self.grid = None
        self.source_text = ""
        self.source_file = None
        self.paste_area.clear()
        self.paste_area.setVisible(False)
        self.analyse_button.setVisible(False)
        self.result_area.clear()
        self.result_file = None
        self.return_area.clear()
        self.allow_partial.setChecked(False)
        self.table.setRowCount(0)
        self._refresh_cycle()
        self.stack.setCurrentIndex(0)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt's own spelling)
        """Closing the window is what loses a cycle, so it asks first."""
        if self.mapping is not None and self.mapping.entries:
            question = QMessageBox(self)
            question.setWindowTitle("Un cycle est en cours")
            question.setIcon(QMessageBox.Warning)
            question.setText("Un cycle est en cours")
            question.setInformativeText(
                f"{len(self.mapping.entries)} correspondance(s) sont en mémoire et "
                "ne sont enregistrées nulle part.\n\n"
                "Si vous fermez maintenant, les vrais noms de ce cycle seront "
                "définitivement perdus et tout document déjà anonymisé deviendra "
                "illisible."
            )
            question.setStandardButtons(QMessageBox.Cancel | QMessageBox.Close)
            question.setDefaultButton(QMessageBox.Cancel)
            question.button(QMessageBox.Close).setText("Fermer quand même")
            question.button(QMessageBox.Cancel).setText("Revenir")
            if question.exec() != QMessageBox.Close:
                event.ignore()
                return
        event.accept()


def _check_event_types() -> None:
    """Refuse to start unless QCloseEvent already exists as a full type.

    This does not prove the macOS crash on quit is gone: it was never
    reproduced here. What it proves is narrower and checkable: the lazy
    initialisation seen in the crash trace no longer happens at closing
    time, because the type is already in the module when the window is
    built.
    """
    created = QtGui.__dict__.get("QCloseEvent")
    if created is not QCloseEvent or not issubclass(QCloseEvent, QEvent):
        raise RuntimeError("QCloseEvent n'est pas initialisé au démarrage")
    probe = QCloseEvent()
    probe.ignore()
    if probe.isAccepted():
        raise RuntimeError("QCloseEvent est incomplet au démarrage")


def _alert(parent: QWidget, icon: QMessageBox.Icon, title: str, body: str) -> None:
    """A message box whose title is printed in the box itself.

    macOS draws no title on a message box: Qt sets it, the platform drops
    it. "Export refusé, rien n'a été écrit" was a window title, so on a Mac
    the one sentence carrying the guarantee was never shown. The title goes
    in the text, which every platform prints, and the detail under it.
    """
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(title)
    box.setInformativeText(body)
    box.exec()


def _masked_stem(stem: str, mapping: Mapping) -> str:
    """The file name that travels with the masked document, masked too.

    The file went out as ``Dossier_Benzaoui_ANON.docx``: the refusal check
    reads every entry inside the package, but not the name of the package
    itself, and the name is what the chat window shows first. A copy of
    the table does the masking, so that a value seen only in the file name
    is not recorded as used by the document, which would make the return
    trip demand a pseudonym the document never contained.
    """
    try:
        return plaintext.anonymize(stem, Mapping(mapping.entries))
    except RefusedExport:
        return "document"


def _unused(path: Path) -> Path:
    """``path``, or the first ``name_2``, ``name_3``… that does not exist.

    The tool writes next to the document, under names it chooses, and
    the file already there may be the one that just came back from the
    AI, saved under the same name, existing nowhere else. A question
    would be clicked through; a new name costs nothing.
    """
    candidate, number = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{number}{path.suffix}")
        number += 1
    return candidate


def _restored_stem(stem: str, mapping: Mapping) -> str:
    restored, _ = plaintext.deanonymize(stem, Mapping(mapping.entries), require_all=False)
    return restored


def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    return item


def main() -> int:
    guard = NetworkGuard.install()
    app = QApplication(sys.argv)
    window = Window(guard)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
