"""The window.

Deliberately thin. Every decision it shows comes from :mod:`workflow`,
every substitution from :mod:`engine` or :mod:`plaintext`, and both are
covered by tests that need no display. What lives here is layout and
wiring, which is the part a test cannot usefully assert anyway.

NOT EXECUTED ANYWHERE IN CI. The test suite runs headless, so this file
is checked by being imported, not by being shown. Until someone opens it
on Windows, treat its behaviour as unverified.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import engine, plaintext, workflow
from .detect import Certainty
from .engine import RefusedExport
from .lexicon import Lexicon
from .mapping import Mapping
from .netguard import NetworkGuard
from .session import Session
from .workflow import Decision

CERTAINTY_LABEL = {
    Certainty.CERTAIN: "Certain",
    Certainty.CONFIRM: "À confirmer",
    Certainty.CASE_LAW: "Jurisprudence",
}


class Window(QMainWindow):
    def __init__(self, guard: NetworkGuard) -> None:
        super().__init__()
        self.guard = guard
        self.session: Session | None = None
        self.grid: workflow.Grid | None = None
        self.source_text = ""
        self.source_file: Path | None = None
        self.workspace = Path.home() / "Documents"
        self.lexicon = Lexicon.load(Path.home() / ".anonymiseur-mots.txt")

        self.setWindowTitle("Anonymiseur de documents")
        self.resize(1100, 740)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.stack.addWidget(self._build_home())
        self.stack.addWidget(self._build_grid())
        self.stack.addWidget(self._build_result())
        self.stack.addWidget(self._build_return())

        self._build_status_bar()

    # ------------------------------------------------------------- chrome
    def _build_status_bar(self) -> None:
        self.network_label = QLabel()
        self.network_label.setContentsMargins(8, 0, 8, 0)
        self.statusBar().addPermanentWidget(self.network_label)
        self._refresh_network_label()

    def _refresh_network_label(self) -> None:
        if self.guard.clean:
            self.network_label.setText("Hors ligne — aucune connexion ouverte")
            self.network_label.setStyleSheet("color: #146c43; font-weight: 600;")
        else:
            self.network_label.setText(
                f"ATTENTION : {self.guard.attempts} tentative(s) de connexion bloquée(s)"
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
            "Masquez les noms avant de soumettre un texte à une IA, puis remettez-les "
            "au retour. Rien ne sort de cet ordinateur."
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

        layout.addWidget(_heading("Reprendre un travail en cours"))
        self.sessions_box = QComboBox()
        layout.addWidget(self.sessions_box)
        resume = QPushButton("Reprendre et remettre les vrais noms")
        resume.clicked.connect(self._resume)
        layout.addWidget(resume)

        self.paste_area = QPlainTextEdit()
        self.paste_area.setPlaceholderText("Collez ici le texte à anonymiser…")
        self.paste_area.setVisible(False)
        layout.addWidget(self.paste_area, stretch=1)

        self.analyse_button = QPushButton("Analyser")
        self.analyse_button.setVisible(False)
        self.analyse_button.clicked.connect(self._analyse_text)
        layout.addWidget(self.analyse_button)

        layout.addStretch()
        self._refresh_sessions()
        return page

    def _refresh_sessions(self) -> None:
        self.sessions_box.clear()
        self.known_sessions = Session.recent(self.workspace)
        for session in self.known_sessions:
            self.sessions_box.addItem(f"{session.label}  ({session.created[:10]})")
        if not self.known_sessions:
            self.sessions_box.addItem("Aucune session enregistrée")

    def _start_text(self) -> None:
        self.paste_area.setVisible(True)
        self.analyse_button.setVisible(True)
        self.paste_area.setFocus()

    def _start_file(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choisir un document Word", str(self.workspace), "Documents Word (*.docx)"
        )
        if not chosen:
            return
        self.source_file = Path(chosen)
        self.workspace = self.source_file.parent
        try:
            text, images = _read_docx(self.source_file)
        except Exception as error:  # noqa: BLE001 - shown to the user as is
            QMessageBox.critical(self, "Lecture impossible", str(error))
            return
        self.source_text = text
        self._open_grid(mode="file", label=self.source_file.stem, images=images)

    def _analyse_text(self) -> None:
        text = self.paste_area.toPlainText().strip()
        if not text:
            return
        self.source_text = text
        self.source_file = None
        self._open_grid(mode="text", label="Texte collé")

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
            "Décochez ce qui ne doit pas être masqué. Les noms de parties dans la "
            "jurisprudence citée sont conservés : les masquer rendrait la citation "
            "incompréhensible."
        )
        self.grid_hint.setWordWrap(True)
        layout.addWidget(self.grid_hint)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Masquer", "Valeur trouvée", "Occurrences", "Remplacée par", "Pourquoi"]
        )
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
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
        row.addWidget(back)
        row.addStretch()
        row.addWidget(run)
        layout.addLayout(row)
        return page

    def _open_grid(self, mode: str, label: str, images: list[str] | None = None) -> None:
        self.grid = workflow.build(self.source_text, images=images, lexicon=self.lexicon)
        self.session = Session.create(self.workspace, label, mode=mode,
                                      source_name=self.source_file.name if self.source_file else "")
        self.grid_heading.setText(f"{len(self.grid.rows)} élément(s) repéré(s) — {label}")
        self._fill_table()
        self.images_label.setText(
            "" if not self.grid.images else
            f"{len(self.grid.images)} image(s) dans ce document. Le texte qu'elles "
            "contiennent (signature scannée, tampon, capture d'écran) n'est pas lu "
            "et n'est donc pas masqué."
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
        layout.addWidget(self.result_area, stretch=1)

        row = QHBoxLayout()
        copy = QPushButton("Copier")
        copy.clicked.connect(self._copy_result)
        done = QPushButton("J'ai la réponse de l'IA, remettre les vrais noms")
        done.setMinimumHeight(40)
        done.clicked.connect(lambda: self.stack.setCurrentIndex(3))
        row.addWidget(copy)
        row.addStretch()
        row.addWidget(done)
        layout.addLayout(row)
        return page

    def _copy_result(self) -> None:
        QApplication.clipboard().setText(self.result_area.toPlainText())

    def _run(self) -> None:
        assert self.grid is not None and self.session is not None
        self._collect_edits()

        conflicts = self.grid.conflicts()
        if conflicts:
            QMessageBox.warning(self, "Table incohérente", "\n".join(conflicts))
            return

        mapping = self.grid.to_mapping()
        try:
            if self.source_file is not None:
                destination = self.source_file.with_name(f"{self.source_file.stem}_ANON.docx")
                engine.anonymize(self.source_file, destination, mapping)
                shown = f"Fichier écrit :\n{destination}"
            else:
                shown = plaintext.anonymize(self.source_text, mapping)
        except RefusedExport as refused:
            QMessageBox.critical(
                self,
                "Export refusé, rien n'a été écrit",
                "Des valeurs réelles subsistent :\n\n"
                + "\n".join(f"• {r.value} ({r.where})" for r in refused.residues[:12]),
            )
            return

        self.session.mapping = mapping
        self.session.save()
        workflow.remember_decisions(self.grid, self.lexicon)
        self.lexicon.save()
        self.result_heading.setText("Version anonyme — à soumettre à l'IA")
        self.result_area.setPlainText(shown)
        self._refresh_network_label()
        self.stack.setCurrentIndex(2)

    # ------------------------------------------------------------- return
    def _build_return(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)

        heading = QLabel("Remettre les vrais noms")
        heading.setFont(QFont(self.font().family(), 15, QFont.Bold))
        layout.addWidget(heading)
        layout.addWidget(QLabel(
            "Collez ici le texte corrigé par l'IA, ou ouvrez le document corrigé."
        ))

        self.return_area = QPlainTextEdit()
        layout.addWidget(self.return_area, stretch=1)

        self.allow_partial = QCheckBox(
            "Ce n'est qu'un extrait : accepter que certains pseudonymes soient absents"
        )
        layout.addWidget(self.allow_partial)

        row = QHBoxLayout()
        open_file = QPushButton("Ouvrir un document corrigé")
        open_file.clicked.connect(self._restore_file)
        restore = QPushButton("Remettre les vrais noms")
        restore.setMinimumHeight(40)
        restore.clicked.connect(self._restore_text)
        row.addWidget(open_file)
        row.addStretch()
        row.addWidget(restore)
        layout.addLayout(row)
        return page

    def _mapping(self) -> Mapping | None:
        if self.session is None:
            QMessageBox.warning(self, "Aucune session", "Ouvrez d'abord une session.")
            return None
        return self.session.mapping

    def _restore_text(self) -> None:
        mapping = self._mapping()
        if mapping is None:
            return
        try:
            restored, missing = plaintext.deanonymize(
                self.return_area.toPlainText(), mapping,
                require_all=not self.allow_partial.isChecked(),
            )
        except RefusedExport as refused:
            self._explain_refusal(refused)
            return
        self.result_heading.setText("Texte restauré")
        self.result_area.setPlainText(restored)
        if missing:
            QMessageBox.information(
                self, "Restauration partielle",
                "Non restaurés :\n" + "\n".join(f"• {v}" for v in missing[:12]),
            )
        self.stack.setCurrentIndex(2)

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
        destination = source.with_name(f"{source.stem.replace('_ANON', '')}_FINAL.docx")
        try:
            engine.deanonymize(source, destination, mapping,
                               require_all=not self.allow_partial.isChecked())
        except RefusedExport as refused:
            self._explain_refusal(refused)
            return
        self.result_heading.setText("Document restauré")
        self.result_area.setPlainText(f"Fichier écrit :\n{destination}")
        self.stack.setCurrentIndex(2)

    def _explain_refusal(self, refused: RefusedExport) -> None:
        QMessageBox.critical(
            self,
            "Restauration refusée, rien n'a été écrit",
            "Ces pseudonymes n'ont pas été retrouvés dans le texte renvoyé. "
            "L'IA les a probablement reformulés, et ils ne peuvent donc plus être "
            "remplacés par les vrais noms :\n\n"
            + "\n".join(f"• {r.value}" for r in refused.residues[:12])
            + "\n\nCorrigez-les dans le texte, ou cochez la case « extrait ».",
        )

    def _resume(self) -> None:
        if not getattr(self, "known_sessions", None):
            return
        self.session = self.known_sessions[self.sessions_box.currentIndex()]
        self.workspace = self.session.folder.parent
        self.stack.setCurrentIndex(3)


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-weight: 600; margin-top: 10px;")
    return label


def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    return item


def _read_docx(path: Path) -> tuple[str, list[str]]:
    """Pull the text out of every story part, for detection only."""
    from . import textmap
    from .package import Package

    package = Package.open(path)
    chunks = [textmap.full_text(textmap.parse(part.data)) for part in package.stories()]
    return "\n".join(chunk for chunk in chunks if chunk), [p.name for p in package.images()]


def main() -> int:
    guard = NetworkGuard.install()
    app = QApplication(sys.argv)
    window = Window(guard)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
