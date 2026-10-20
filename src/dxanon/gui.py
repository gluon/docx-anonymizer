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
from PySide6.QtGui import (
    QCloseEvent, QColor, QDesktopServices, QFont, QKeySequence, QShortcut,
    QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QTextEdit,
    QVBoxLayout, QWidget,
)

from . import engine, plaintext, workflow
from .case import SUFFIX, Case, unused
from .detect import Certainty
from .engine import EmptyTable
from .mapping import Mapping
from .netguard import NetworkGuard
from .workflow import Decision

#: Index of the help page in the stack, so the other screens stay 0..3.
#: The two case screens are appended after it rather than inserted, so
#: that this number, which is read in several places, does not move.
HELP = 4
DOSSIER = 5
CASE_RESULTS = 6
READER = 7

#: The one action of each screen, painted rather than left to the theme.
#:
#: Qt asks the platform to draw a default button, and macOS drew this one
#: light grey on white: the button that carries the whole screen read as
#: disabled. Which button a theme highlights, and how, is not something
#: this program can test for, so it stops asking: the colours are fixed
#: here, and their contrast is checked by a test rather than by looking.
#:
#: The disabled state is spelled out too. Without it, Qt keeps the
#: stylesheet's background and only greys the label, so a button that
#: cannot be clicked still looks like the one that can.
PRIMARY_BACKGROUND = "#1f4f8b"
PRIMARY_TEXT = "#ffffff"
PRIMARY_STYLE = f"""
QPushButton {{
  background-color: {PRIMARY_BACKGROUND};
  color: {PRIMARY_TEXT};
  border: 1px solid #16375f;
  border-radius: 6px;
  padding: 8px 16px;
  font-weight: 600;
}}
QPushButton:hover    {{ background-color: #1a4478; }}
QPushButton:pressed  {{ background-color: #143a66; }}
QPushButton:disabled {{
  background-color: #e4e6e9;
  color: #5c6166;
  border: 1px solid #c9ccd1;
}}
"""


def primary(button: QPushButton) -> QPushButton:
    """Mark a button as the action of its screen."""
    button.setStyleSheet(PRIMARY_STYLE)
    button.setDefault(True)
    button.setMinimumHeight(40)
    return button

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
        #: Everything the window works on, always. A single document is
        #: a case with one piece: the first version kept the simple flow
        #: separate and added "if a case is open" to every screen, which
        #: doubled every path in the one layer no test here can run. One
        #: object, one path; what differs between a document and a case
        #: is what is shown, which is a question the screens answer from
        #: the number of pieces.
        self.case: Case = Case()
        self.outcomes: list = []
        #: Where the case's table was last written, so closing can offer
        #: to write it again without asking where.
        self.case_file: Path | None = None

        self.setWindowTitle("Anonymiseur de documents")
        self.resize(1100, 740)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.stack.addWidget(self._build_home())
        self.stack.addWidget(self._build_grid())
        self.stack.addWidget(self._build_result())
        self.stack.addWidget(self._build_return())
        self.stack.addWidget(self._build_help())
        self.stack.addWidget(self._build_dossier())
        self.stack.addWidget(self._build_case_results())
        self.stack.addWidget(self._build_reader())

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
        dossier = QPushButton("Un dossier, plusieurs pièces")
        dossier.clicked.connect(self._start_case)
        for button in (paste, open_file, dossier):
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
        # The placeholder disappears with the first paste; the name stays,
        # for a screen reader and for whoever comes back to the screen.
        self.paste_area.setAccessibleName("Texte à anonymiser")
        self.paste_area.setVisible(False)
        layout.addWidget(self.paste_area, stretch=1)

        self.analyse_button = primary(QPushButton("Analyser"))
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
        summary = self.case.summary()
        self.resume_button.setVisible(bool(summary))
        kept = (f"Table enregistrée : {self.case_file.name}" if self.case_file
                else "Ne fermez pas la fenêtre.")
        self.cycle_label.setText(f"{summary} {kept}" if summary else "")
        self.cycle_label.setStyleSheet("color: #d08700; font-weight: 600;")

    def _start_text(self) -> None:
        self.paste_area.setVisible(True)
        self.analyse_button.setVisible(True)
        self.paste_area.setFocus()

    def _fresh_case(self) -> bool:
        """Start a case over, having asked if one is already in progress."""
        if not self._may_start_over():
            return False
        self.case = Case()
        self.case_file = None
        self.outcomes = []
        return True

    def _may_start_over(self) -> bool:
        """Ask before a new analysis replaces the table of a cycle in progress.

        Opening another document used to drop the current table without a
        word: the same loss as closing the window, which asks. So this asks
        the same question, with "Revenir" as the default.
        """
        if not self.case.names:
            return True
        question = QMessageBox(self)
        question.setWindowTitle("Un cycle est en cours")
        question.setIcon(QMessageBox.Warning)
        question.setText("Un cycle est en cours")
        question.setInformativeText(
            f"{self.case.names} correspondance(s) sont en mémoire et "
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
        # Asked before the file picker, not after. Reversed, the window
        # offered to choose a document and only then said that choosing
        # one would lose the names of the cycle in progress, which is
        # backwards; and a test that had encoded the order held the
        # Windows job for ten minutes on a native dialog nobody could
        # answer.
        if not self._fresh_case():
            return
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choisir un document Word", str(self.workspace), "Documents Word (*.docx)"
        )
        if not chosen:
            return
        path = Path(chosen)
        self.workspace = path.parent
        try:
            self.case.add_file(path)
        except Exception as error:  # noqa: BLE001 - shown to the user as is
            _alert(self, QMessageBox.Critical, "Lecture impossible", str(error))
            return
        self._analyse(path.stem)

    def _analyse_text(self) -> None:
        text = self.paste_area.toPlainText().strip()
        if not text:
            _alert(self, QMessageBox.Information, "Rien à analyser",
                   "La zone est vide. Collez-y le texte à anonymiser.")
            return
        if not self._fresh_case():
            return
        self.case.add_text("Texte collé", text)
        self._analyse("Texte collé")

    def _analyse(self, label: str) -> None:
        """Read every piece, then show the one grid they produce."""
        missing = self.case.reread()
        if missing:
            _alert(self, QMessageBox.Warning, "Pièces introuvables",
                   "Ces pièces ne sont plus à l'endroit enregistré :\n"
                   + "\n".join(f"• {name}" for name in missing))
        self.grid = self.case.analyse()
        self._show_grid(f"{len(self.grid.rows)} élément(s) repéré(s) — {label}")

    # --------------------------------------------------------------- grid
    def _build_grid(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        self.grid_heading = QLabel()
        self.grid_heading.setFont(QFont(self.font().family(), 15, QFont.Bold))
        layout.addWidget(self.grid_heading)

        self.grid_hint = QLabel(
            "Décochez ce qui ne doit pas être masqué. "
            "Double-cliquez sur un pseudonyme pour le changer."
        )
        self.grid_hint.setWordWrap(True)
        layout.addWidget(self.grid_hint)

        self.table = QTableWidget(0, 5)
        # Tab leaves the table; the arrows still move between cells.
        self.table.setTabKeyNavigation(False)
        self.table.setAccessibleName("Éléments repérés")
        self.table.setHorizontalHeaderLabels(
            ["Masquer", "Valeur trouvée", "Occurrences", "Remplacée par", "Pourquoi"]
        )
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        # The pseudonym is what the user reads and retypes before trusting
        # the export, so it is sized to its own contents rather than to a
        # share of the window. Stretching it was enough on macOS and not
        # on Windows, where the default font is wider: "ORION INDUSTRIES
        # DU BEAUVOIR" asked for 348 pixels and was given 273.
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
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
        reader = QPushButton("Relire le texte")
        reader.clicked.connect(self._open_reader)
        row.addWidget(reader)
        self.run_button = run = primary(QPushButton("Produire la version anonyme"))
        run.clicked.connect(self._run)
        row.addWidget(back)
        row.addStretch()
        row.addWidget(run)
        layout.addLayout(row)
        QWidget.setTabOrder(self.table, run)
        QWidget.setTabOrder(run, back)
        return page

    def _show_grid(self, heading: str) -> None:
        """One grid screen for a document and for a case.

        A case adds one column, saying which pieces each value appears
        in. A name in one piece out of nine is worth a second look; a
        name in all nine rarely is. The column is added rather than
        always present, because an empty column in the simple flow is a
        thing to read and dismiss on every single document.
        """
        several = len(self.case.pieces) > 1
        headings = ["Masquer", "Valeur trouvée", "Occurrences", "Remplacée par", "Pourquoi"]
        self.table.setColumnCount(6 if several else 5)
        self.table.setHorizontalHeaderLabels(headings + (["Pièces"] if several else []))
        if several:
            self.table.horizontalHeader().setSectionResizeMode(
                5, QHeaderView.ResizeToContents)
        self.run_button.setText(
            "Produire les pièces anonymes" if several else "Produire la version anonyme")
        self.grid_heading.setText(heading)
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

            self.table.setItem(index, 1, _cell(row.value, tip=row.value))
            self.table.setItem(index, 2, _cell(str(row.occurrences)))
            pseudonym = QTableWidgetItem(row.pseudonym)
            # The text itself goes in the tooltip, not only the hint: a
            # column can always end up narrower than its content, on a
            # small window or a platform whose font is wider, and this is
            # the one column the user has to read before trusting the
            # export.
            pseudonym.setToolTip(
                f"{row.pseudonym}\n\nDouble-cliquez pour changer ce pseudonyme"
                if row.pseudonym else "Double-cliquez pour changer ce pseudonyme"
            )
            self.table.setItem(index, 3, pseudonym)
            why = f"{CERTAINTY_LABEL[row.certainty]} — {row.why}"
            self.table.setItem(index, 4, _cell(why, tip=why))
            if self.table.columnCount() > 5:
                pieces = ", ".join(row.pieces)
                self.table.setItem(index, 5, _cell(pieces, tip=pieces))

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
        self.result_area.setAccessibleName("Résultat")
        layout.addWidget(self.result_area, stretch=1)

        row = QHBoxLayout()
        self.copy_button = copy = QPushButton("Copier")
        copy.clicked.connect(self._copy_result)
        self.restart_button = restart = QPushButton("Effacer le cycle")
        # Not connect(self._reset): clicked passes checked=False, which
        # landed in ``confirm`` and cleared the cycle without asking.
        restart.clicked.connect(lambda: self._reset())
        self.done_button = done = primary(
            QPushButton("J'ai la réponse de l'IA, remettre les vrais noms"))
        done.clicked.connect(self._open_return)
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
        # Nothing showed the copy had happened, so people copied twice, or
        # went to the chat unsure. The label says it until the next result.
        self.copy_button.setText("Copié ✓")

    def _run(self) -> None:
        assert self.grid is not None
        self._collect_edits()

        conflicts = self.grid.conflicts()
        if conflicts:
            _alert(self, QMessageBox.Warning, "Table incohérente", "\n".join(conflicts))
            return

        folder = None
        if len(self.case.pieces) > 1:
            chosen = QFileDialog.getExistingDirectory(
                self, "Où écrire les pièces anonymisées", str(self.workspace))
            if not chosen:
                return
            folder = self.workspace = Path(chosen)

        try:
            self.outcomes = self.case.export(folder=folder)
        except EmptyTable:
            _alert(
                self, QMessageBox.Warning,
                "Rien n'est coché, rien n'a été écrit",
                "Sans aucune valeur à masquer, la « version anonyme » serait "
                "l'original sous un autre nom. Cochez au moins une ligne de la grille.",
            )
            return

        self.mapping = self.case.table
        self._refresh_cycle()
        self._refresh_network_label()
        self._show_outcomes()

    def _show_outcomes(self) -> None:
        """One piece reads as a result; several read as a list.

        A single document showing a one-row table of results would be a
        screen asking to be read before it says anything, so it keeps
        the result screen it always had. The refusal, for one piece, is
        the only thing on screen, so it is a dialog; among several it is
        a line beside the piece it concerns.
        """
        if len(self.outcomes) == 1:
            only = self.outcomes[0]
            if not only.ok:
                _alert(
                    self, QMessageBox.Critical,
                    "Export refusé, rien n'a été écrit",
                    "Des valeurs réelles subsistent :\n\n"
                    + "\n".join(f"• {value}" for value in only.refused[:12]),
                )
                return
            self._show_result("Version anonyme — à soumettre à l'IA",
                              only.text or "", only.written)
            return
        self._show_case_results()

    # ------------------------------------------------------------- return
    def _build_return(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)

        heading = QLabel("Remettre les vrais noms")
        heading.setFont(QFont(self.font().family(), 15, QFont.Bold))
        layout.addWidget(heading)
        prompt = QLabel("Collez le texte corrigé, ou ouvrez le document corrigé.")
        layout.addWidget(prompt)

        self.return_area = QPlainTextEdit()
        self.return_area.setTabChangesFocus(True)
        self.return_area.setAccessibleName("Texte renvoyé par l'IA")
        prompt.setBuddy(self.return_area)
        layout.addWidget(self.return_area, stretch=1)

        self.allow_partial = QCheckBox(
            "Je ne colle qu'une partie du texte : ne pas exiger tous les pseudonymes"
        )
        layout.addWidget(self.allow_partial)

        # Which piece is coming back. A case's table holds the pseudonyms
        # of every piece, and the check that a pseudonym has not been
        # reworded can only be asked of the piece that carried it: asked
        # of the whole case, every piece is refused for the names it
        # never contained. Left on "detect", a document is recognised by
        # the name it was written under and a single piece needs no
        # answer at all.
        self.piece_row = QWidget()
        piece_layout = QHBoxLayout(self.piece_row)
        piece_layout.setContentsMargins(0, 0, 0, 0)
        piece_label = QLabel("Pièce concernée :")
        self.piece_choice = QComboBox()
        self.piece_choice.setAccessibleName("Pièce concernée")
        piece_label.setBuddy(self.piece_choice)
        piece_layout.addWidget(piece_label)
        piece_layout.addWidget(self.piece_choice, stretch=1)
        self.piece_row.setVisible(False)
        layout.addWidget(self.piece_row)

        row = QHBoxLayout()
        # The only screen without a way back: reached by mistake, it could
        # be left only by starting a restoration or through the help.
        back = QPushButton("Retour")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(self._return_from))
        open_file = QPushButton("Ouvrir un document corrigé")
        open_file.clicked.connect(self._restore_file)
        restore = primary(QPushButton("Remettre les vrais noms"))
        restore.clicked.connect(self._restore_text)
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
        self.piece_row.setVisible(len(self.case.pieces) > 1)
        self.piece_choice.clear()
        self.piece_choice.addItem("Reconnaître automatiquement", None)
        for piece in self.case.pieces:
            self.piece_choice.addItem(piece.label, piece.label)
        self.stack.setCurrentIndex(3)

    def _chosen_piece(self) -> str | None:
        return self.piece_choice.currentData() if self.piece_row.isVisible() else None

    def _mapping(self) -> Mapping | None:
        self.mapping = self.case.table
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
        self._finish(self.case.restore_text(
            self.return_area.toPlainText(), label=self._chosen_piece(),
            allow_partial=self.allow_partial.isChecked(),
        ), "Texte restauré", mapping)

    def _finish(self, outcome, heading: str, mapping: Mapping) -> None:
        """One ending for both restorations: refused, partial, or done."""
        if not outcome.ok:
            self._explain_refusal(outcome, mapping)
            return
        self._show_result(heading, outcome.text or "", outcome.written, restored=True)
        if outcome.unresolved:
            _alert(
                self, QMessageBox.Information, "Restauration partielle",
                "Non restaurés :\n"
                + "\n".join(f"• {value}" for value in outcome.unresolved[:12]),
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
        corrected = Path(chosen)
        stem = _restored_stem(corrected.stem.replace("_ANON", ""), mapping)
        self._finish(self.case.restore_file(
            corrected,
            destination=unused(corrected.with_name(f"{stem}_FINAL.docx")),
            label=self._chosen_piece(),
            allow_partial=self.allow_partial.isChecked(),
        ), "Document restauré", mapping)

    def _explain_refusal(self, outcome, mapping: Mapping) -> None:
        expected = [e for e in mapping.entries if e.pseudonym and mapping.was_used(e)]
        if len(outcome.refused) >= len(expected):
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
        several = len(self.case.pieces) > 1
        _alert(
            self, QMessageBox.Critical,
            "Restauration refusée, rien n'a été écrit",
            (f"Pièce : {outcome.label}\n\n" if several else "")
            + "Ces pseudonymes n'ont pas été retrouvés dans le texte renvoyé. "
            "L'IA les a probablement reformulés, et ils ne peuvent donc plus être "
            "remplacés par les vrais noms :\n\n"
            + "\n".join(f"• {value}" for value in outcome.refused[:12])
            + "\n\nCorrigez-les dans le texte, cochez « Je ne colle qu'une partie "
            "du texte », ou vérifiez la pièce choisie.",
        )

    # ------------------------------------------------------------ dossier
    def _build_dossier(self) -> QWidget:
        """The pieces of one case, before anything is analysed.

        Two buttons and a list. A case screen that asked for a name, a
        reference, a client and a folder before the first document would
        be a form, and a form is what makes people go back to doing it by
        hand.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        heading = QLabel("Un dossier")
        heading.setFont(QFont(self.font().family(), 15, QFont.Bold))
        layout.addWidget(heading)
        layout.addWidget(QLabel(
            "Un même nom reçoit le même pseudonyme dans toutes les pièces."
        ))

        self.pieces_table = QTableWidget(0, 2)
        self.pieces_table.setTabKeyNavigation(False)
        self.pieces_table.setAccessibleName("Pièces du dossier")
        self.pieces_table.setHorizontalHeaderLabels(["Pièce", "Nature"])
        self.pieces_table.verticalHeader().setVisible(False)
        self.pieces_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.pieces_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents)
        layout.addWidget(self.pieces_table, stretch=1)

        self.case_paste = QPlainTextEdit()
        self.case_paste.setTabChangesFocus(True)
        self.case_paste.setPlaceholderText("Collez ici le contenu d'un mail, puis « Ajouter ce texte »…")
        self.case_paste.setAccessibleName("Texte à ajouter au dossier")
        self.case_paste.setVisible(False)
        layout.addWidget(self.case_paste)

        add_row = QHBoxLayout()
        add_file = QPushButton("Ajouter un document Word")
        add_file.clicked.connect(self._case_add_file)
        add_text = QPushButton("Ajouter un texte collé")
        add_text.clicked.connect(self._case_show_paste)
        self.case_add_text_button = QPushButton("Ajouter ce texte")
        self.case_add_text_button.setVisible(False)
        self.case_add_text_button.clicked.connect(self._case_add_text)
        drop = QPushButton("Retirer la pièce choisie")
        drop.clicked.connect(self._case_remove)
        for button in (add_file, add_text, self.case_add_text_button, drop):
            add_row.addWidget(button)
        add_row.addStretch()
        layout.addLayout(add_row)

        row = QHBoxLayout()
        back = QPushButton("Retour")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        reopen = QPushButton("Reprendre une table enregistrée")
        reopen.clicked.connect(self._case_load)
        self.case_analyse = primary(QPushButton("Analyser le dossier"))
        self.case_analyse.clicked.connect(self._case_analyse)
        row.addWidget(back)
        row.addWidget(reopen)
        row.addStretch()
        row.addWidget(self.case_analyse)
        layout.addLayout(row)
        return page

    def _start_case(self) -> None:
        if not self.case.pieces and not self._fresh_case():
            return
        self._refresh_pieces()
        self.stack.setCurrentIndex(DOSSIER)

    def _refresh_pieces(self) -> None:
        pieces = self.case.pieces
        self.pieces_table.setRowCount(len(pieces))
        for index, piece in enumerate(pieces):
            self.pieces_table.setItem(index, 0, _cell(piece.label, tip=piece.label))
            self.pieces_table.setItem(
                index, 1, _cell("Document Word" if piece.is_file else "Texte collé"))
        self.case_analyse.setEnabled(bool(pieces))

    def _case_add_file(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Ajouter un document au dossier", str(self.workspace),
            "Documents Word (*.docx)",
        )
        if not chosen:
            return
        path = Path(chosen)
        self.workspace = path.parent
        try:
            self.case.add_file(path)
        except Exception as error:  # noqa: BLE001 - shown to the user as is
            _alert(self, QMessageBox.Warning, "Pièce non ajoutée", str(error))
            return
        self._refresh_pieces()

    def _case_show_paste(self) -> None:
        self.case_paste.setVisible(True)
        self.case_add_text_button.setVisible(True)
        self.case_paste.setFocus()

    def _case_add_text(self) -> None:
        text = self.case_paste.toPlainText().strip()
        if not text:
            _alert(self, QMessageBox.Information, "Rien à ajouter",
                   "La zone est vide. Collez-y le contenu à anonymiser.")
            return
        pasted = sum(1 for p in self.case.pieces if not p.is_file)
        self.case.add_text(f"Texte collé {pasted + 1}", text)
        self.case_paste.clear()
        self.case_paste.setVisible(False)
        self.case_add_text_button.setVisible(False)
        self._refresh_pieces()

    def _case_remove(self) -> None:
        index = self.pieces_table.currentRow()
        if index < 0 or index >= len(self.case.pieces):
            _alert(self, QMessageBox.Information, "Aucune pièce choisie",
                   "Cliquez d'abord sur la ligne de la pièce à retirer.")
            return
        self.case.remove(self.case.pieces[index].label)
        self._refresh_pieces()

    def _case_analyse(self) -> None:
        if self.case.pieces:
            self._analyse(f"dossier, {len(self.case.pieces)} pièce(s)")

    def _case_load(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Reprendre une table de dossier", str(self.workspace),
            f"Tables de noms (*{SUFFIX});;Tous les fichiers (*)",
        )
        if not chosen:
            return
        try:
            self.case = Case.load(Path(chosen))
        except Exception as error:  # noqa: BLE001 - shown to the user as is
            _alert(self, QMessageBox.Critical, "Table illisible", str(error))
            return
        self.case_file = Path(chosen)
        self.mapping = self.case.table
        self._refresh_pieces()
        self._refresh_cycle()
        _alert(self, QMessageBox.Information, "Dossier repris",
               f"{len(self.case.table.entries)} correspondance(s) reprises. "
               "Vous pouvez restituer les vrais noms, ou analyser à nouveau "
               "le dossier pour y ajouter une pièce.")

    # ----------------------------------------------------- case, the result
    def _build_case_results(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        self.case_result_heading = QLabel()
        self.case_result_heading.setFont(QFont(self.font().family(), 15, QFont.Bold))
        layout.addWidget(self.case_result_heading)

        self.case_results_table = QTableWidget(0, 3)
        self.case_results_table.setTabKeyNavigation(False)
        self.case_results_table.setAccessibleName("Pièces produites")
        self.case_results_table.setHorizontalHeaderLabels(["Pièce", "Résultat", ""])
        self.case_results_table.verticalHeader().setVisible(False)
        self.case_results_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self.case_results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.case_results_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents)
        layout.addWidget(self.case_results_table, stretch=1)

        self.case_refusals = QLabel()
        self.case_refusals.setWordWrap(True)
        self.case_refusals.setStyleSheet("color: #b02a37; font-weight: 700;")
        layout.addWidget(self.case_refusals)

        row = QHBoxLayout()
        back = QPushButton("Retour à la grille")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        save = QPushButton("Enregistrer la table du dossier")
        save.clicked.connect(self._case_save)
        done = primary(QPushButton("J'ai les réponses de l'IA, remettre les vrais noms"))
        done.clicked.connect(self._open_return)
        row.addWidget(back)
        row.addWidget(save)
        row.addStretch()
        row.addWidget(done)
        layout.addLayout(row)
        return page

    def _show_case_results(self) -> None:
        """What became of each piece.

        A piece that is refused does not stop the others: nothing was
        written for it, and a case of nine pieces where one holds a
        surviving name is a case where eight are ready. The refusals are
        named on the same screen rather than in a dialog that has to be
        dismissed before the list can be read.
        """
        written = [o for o in self.outcomes if o.ok]
        refused = [o for o in self.outcomes if not o.ok]
        self.case_result_heading.setText(
            f"{len(written)} pièce(s) produite(s)"
            + (f", {len(refused)} refusée(s)" if refused else "")
        )
        self.case_results_table.setRowCount(len(self.outcomes))
        for index, outcome in enumerate(self.outcomes):
            self.case_results_table.setItem(index, 0, _cell(outcome.label, tip=outcome.label))
            detail = outcome.description
            self.case_results_table.setItem(index, 1, _cell(detail, tip=detail))
            if outcome.ok:
                action = QPushButton(
                    "Ouvrir le dossier" if outcome.written else "Copier")
                action.clicked.connect(lambda _=False, o=outcome: self._case_take(o))
                self.case_results_table.setCellWidget(index, 2, action)
        self.case_refusals.setText(
            "" if not refused else
            "Rien n'a été écrit pour les pièces refusées : une valeur réelle y "
            "survivait au masquage. Revenez à la grille et vérifiez les "
            "pseudonymes concernés."
        )
        self.stack.setCurrentIndex(CASE_RESULTS)

    def _case_take(self, outcome) -> None:
        if outcome.written is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(outcome.written.parent)))
            return
        QApplication.clipboard().setText(outcome.text or "")

    def _case_save(self) -> None:
        suggested = self.case_file or (self.workspace / f"dossier{SUFFIX}")
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer la table du dossier", str(suggested),
            f"Tables de noms (*{SUFFIX})",
        )
        if not chosen:
            return
        try:
            self.case_file = self.case.save(Path(chosen))
        except Exception as error:  # noqa: BLE001 - shown to the user as is
            _alert(self, QMessageBox.Critical, "Enregistrement impossible", str(error))
            return
        _alert(
            self, QMessageBox.Information, "Table enregistrée",
            f"{self.case_file}\n\nCe fichier contient les vrais noms du dossier. "
            "Il ne doit pas être transmis, ni joint à un courriel, ni déposé "
            "dans un espace partagé.",
        )

    # ------------------------------------------------------------- relecture
    def _build_reader(self) -> QWidget:
        """The text, with what will be masked shown in it.

        A grid says "DUPONT, 14 occurrences". It cannot say that the
        nickname in the third paragraph, or the number of the machine
        the client worked on, names him just as surely. Over-detection
        is exhaustive for capitalised names and for nothing else, and
        the one who can see the rest is the one reading.

        So the text is on screen, highlighted where it will change, and
        a selection can be added to the grid. It is also the only screen
        that answers "what will actually go out", which no table can.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        self.reader_heading = QLabel()
        self.reader_heading.setFont(QFont(self.font().family(), 15, QFont.Bold))
        layout.addWidget(self.reader_heading)
        self.reader_hint = QLabel("Sélectionnez ce qui doit être masqué, puis Ctrl+M.")
        layout.addWidget(self.reader_hint)

        self.reader_choice = QComboBox()
        self.reader_choice.setAccessibleName("Pièce à relire")
        self.reader_choice.currentIndexChanged.connect(self._reader_show_piece)
        self.reader_row = QWidget()
        row = QHBoxLayout(self.reader_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Pièce :"))
        row.addWidget(self.reader_choice, stretch=1)
        self.reader_row.setVisible(False)
        layout.addWidget(self.reader_row)

        self.reader_area = QTextEdit()
        self.reader_area.setReadOnly(True)
        self.reader_area.setTabChangesFocus(True)
        self.reader_area.setAccessibleName("Texte relu")
        layout.addWidget(self.reader_area, stretch=1)

        bottom = QHBoxLayout()
        back = QPushButton("Retour à la grille")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        mask = primary(QPushButton("Masquer la sélection"))
        mask.clicked.connect(self._mask_selection)
        bottom.addWidget(back)
        bottom.addStretch()
        bottom.addWidget(mask)
        layout.addLayout(bottom)

        shortcut = QShortcut(QKeySequence("Ctrl+M"), page)
        shortcut.setContext(Qt.WindowShortcut)
        shortcut.activated.connect(self._mask_selection)
        return page

    def _open_reader(self) -> None:
        pieces = self.case.pieces
        if not pieces:
            return
        self.reader_row.setVisible(len(pieces) > 1)
        self.reader_choice.blockSignals(True)
        self.reader_choice.clear()
        for piece in pieces:
            self.reader_choice.addItem(piece.label, piece.label)
        self.reader_choice.blockSignals(False)
        self._reader_show_piece()
        self.stack.setCurrentIndex(READER)

    def _reader_piece(self):
        label = self.reader_choice.currentData()
        return next((p for p in self.case.pieces if p.label == label), self.case.pieces[0])

    def _reader_show_piece(self) -> None:
        piece = self._reader_piece()
        self.reader_heading.setText(f"Relire — {piece.label}")
        if self.reader_area.toPlainText() != piece.text:
            self.reader_area.setPlainText(piece.text)
        self._highlight()

    def _highlight(self) -> None:
        """Paint every value the grid will replace.

        Painted as extra selections rather than written into the
        document, so the text itself is never altered: what is on screen
        is the piece, character for character, and the offsets a
        selection reports are the piece's own.
        """
        assert self.grid is not None
        marked = QTextCharFormat()
        marked.setBackground(QColor("#ffe8a3"))
        kept = QTextCharFormat()
        kept.setBackground(QColor("#e4e6e9"))

        text = self.reader_area.toPlainText()
        selections = []
        for row in self.grid.rows:
            if not row.value:
                continue
            style = marked if row.decision is Decision.REPLACE else kept
            start = text.find(row.value)
            while start >= 0:
                cursor = QTextCursor(self.reader_area.document())
                cursor.setPosition(start)
                cursor.setPosition(start + len(row.value), QTextCursor.KeepAnchor)
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                selection.format = style
                selections.append(selection)
                start = text.find(row.value, start + len(row.value))
        self.reader_area.setExtraSelections(selections)
        self.reader_hint.setText(
            f"{len(selections)} passage(s) surlignés. Sélectionnez, puis Ctrl+M."
        )

    def _mask_selection(self) -> None:
        if self.stack.currentIndex() != READER or self.grid is None:
            return
        chosen = self.reader_area.textCursor().selectedText().strip()
        if not chosen:
            _alert(self, QMessageBox.Information, "Rien n'est sélectionné",
                   "Sélectionnez dans le texte ce qui doit être masqué.")
            return
        try:
            row = workflow.add_by_hand(self.grid, chosen, self._reader_piece().text)
        except ValueError as error:
            _alert(self, QMessageBox.Information, "Rien à masquer", str(error))
            return
        self._fill_table()
        self._highlight()
        self.reader_hint.setText(
            f"« {row.value} » sera remplacé par « {row.pseudonym} »."
        )

    # -------------------------------------------------------------- reset
    def _reset(self, confirm: bool = True) -> None:
        """Clear the cycle. There is nothing on disk to clear with it.

        Forgetting the table is the whole operation, because the table
        was never written anywhere. That is also why it is worth a
        confirmation: once dropped, a document already masked can never
        be turned back.
        """
        if confirm and self.case.names:
            question = QMessageBox(self)
            question.setWindowTitle("Effacer le cycle")
            question.setIcon(QMessageBox.Warning)
            question.setText("Effacer le cycle ?")
            question.setInformativeText(
                f"Les {self.case.names} correspondance(s) en mémoire seront effacées. "
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
        self.case = Case()
        self.case_file = None
        self.outcomes = []
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
        if self.case.names and self.case_file is None:
            question = QMessageBox(self)
            question.setWindowTitle("Un cycle est en cours")
            question.setIcon(QMessageBox.Warning)
            question.setText("Un cycle est en cours")
            question.setInformativeText(
                f"{self.case.names} correspondance(s) sont en mémoire et "
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


def _restored_stem(stem: str, mapping: Mapping) -> str:
    restored, _ = plaintext.deanonymize(stem, Mapping(mapping.entries), require_all=False)
    return restored


def _cell(text: str, tip: str = "") -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if tip:
        item.setToolTip(tip)
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
