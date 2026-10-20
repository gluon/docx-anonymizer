"""A case: several pieces, one table of names.

The property the whole thing exists for: the same person carries the same
pseudonym in every piece. Everything else here protects it, or protects
the file that holds it.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures  # noqa: E402
from dxanon import textmap  # noqa: E402
from dxanon.case import SUFFIX, WARNING, Case  # noqa: E402
from dxanon.workflow import Decision  # noqa: E402

CONCLUSIONS = """CONSEIL DE PRUD'HOMMES DE MARSEILLE
POUR : Madame Sophie LENOIR, demeurant 27 boulevard Chave, 13005 Marseille.
CONTRE : la SAS THERMOPACK INDUSTRIE, prise en la personne de Karim Benhaddou.
La Cour a juge en ce sens (Cass. soc., 8 juillet 2020, Societe Novandie).
Madame LENOIR demande la nullite du licenciement.
"""

MAIL = """Bonjour Maitre,
Sophie a recu la convocation vendredi, remise par Karim Benhaddou.
Son numero de securite sociale est le 2 85 07 13 055 042 12.
Elle ecrit depuis sophie.lenoir@orange.fr.
Thomas Reybaud, delegue syndical, confirme.
"""


def text_of(path, name="word/document.xml") -> str:
    with zipfile.ZipFile(path) as archive:
        return textmap.full_text(textmap.parse(archive.read(name)))


class OneTableForEveryPiece(unittest.TestCase):
    def setUp(self):
        self.case = Case(name="Lenoir c/ Thermopack")
        self.case.add_text("conclusions", CONCLUSIONS)
        self.case.add_text("mail", MAIL)
        self.grid = self.case.analyse()
        self.rows = {row.value: row for row in self.grid.rows}

    def test_the_client_has_one_name_across_the_pieces(self):
        """Masked piece by piece she was two people, which is the point."""
        self.assertEqual(
            self.rows["Sophie LENOIR"].group, self.rows["Sophie"].group,
        )
        self.assertEqual(
            self.rows["Sophie LENOIR"].pseudonym.split()[-1].upper(),
            self.rows["LENOIR"].pseudonym.upper(),
        )

    def test_a_row_says_which_pieces_it_came_from(self):
        self.assertEqual(self.rows["Thomas Reybaud"].pieces, ("mail",))
        self.assertEqual(self.rows["LENOIR"].pieces, ("conclusions",))
        self.assertEqual(set(self.rows["Karim Benhaddou"].pieces),
                         {"conclusions", "mail"})

    def test_a_value_in_two_pieces_is_counted_in_both(self):
        self.assertEqual(self.rows["Karim Benhaddou"].occurrences, 2)

    def test_a_value_seen_in_one_piece_only_is_still_masked(self):
        self.assertIs(self.rows["Thomas Reybaud"].decision, Decision.REPLACE)

    def test_the_identifier_of_one_piece_is_in_the_case_table(self):
        self.assertIn("2 85 07 13 055 042 12", self.rows)

    def test_a_cited_party_is_kept_for_the_whole_case(self):
        self.assertIs(self.rows["Novandie"].decision, Decision.KEEP)

    def test_the_table_is_coherent(self):
        self.assertEqual(self.grid.conflicts(), [])

    def test_every_piece_is_masked_in_one_go(self):
        outcomes = self.case.export()
        self.assertEqual([o.label for o in outcomes], ["conclusions", "mail"])
        self.assertTrue(all(o.ok for o in outcomes), [o.refused for o in outcomes])
        for outcome in outcomes:
            for name in ("Lenoir", "LENOIR", "Sophie", "Benhaddou", "Thermopack",
                         "Reybaud", "orange.fr"):
                self.assertNotIn(name, outcome.text, f"{name} in {outcome.label}")

    def test_the_same_pseudonym_is_written_in_both_pieces(self):
        """The whole point: one person, one name, in every piece."""
        masked = {o.label: o.text for o in self.case.export()}
        employer = self.rows["Karim Benhaddou"].pseudonym
        self.assertIn(employer, masked["mail"])
        self.assertIn(employer, masked["conclusions"])

    def test_the_town_of_the_court_is_not_given_a_first_name(self):
        """The masked pleading was addressed to "PRUD'HOMMES DE DAMIEN"."""
        masked = {o.label: o.text for o in self.case.export()}
        line = masked["conclusions"].splitlines()[0]
        self.assertNotIn(self.rows["Sophie LENOIR"].pseudonym.split()[0].upper(), line)

    def test_the_round_trip_gives_both_pieces_back(self):
        masked = {o.label: o.text for o in self.case.export()}
        for label, original in (("conclusions", CONCLUSIONS), ("mail", MAIL)):
            outcome = self.case.restore_text(masked[label])
            self.assertTrue(outcome.ok, outcome.refused)
            self.assertEqual(outcome.text, original)


class AStatedLimit(unittest.TestCase):
    def test_a_citation_broken_by_a_line_break_loses_its_party(self):
        """Deliberate, and the safer of the two mistakes.

        A citation zone stops at a line break. A mail hard-wrapped at
        column 76 can therefore split "(Cass. soc. ..., Societe\nNovandie)"
        and the party is masked like any other name: the citation is
        spoiled, which is visible and correctable.

        Letting a zone cross the line break is the other mistake, and it
        is invisible: in a short extract naming the client once, right
        after a citation, the client would be marked "keep" and go out in
        clear.
        """
        case = Case()
        case.add_text("piece", "Voir (Cass. soc., 8 juillet 2020, Societe\nNovandie) sur ce point.")
        rows = {row.value: row for row in case.analyse().rows}
        self.assertIs(rows["Novandie"].decision, Decision.REPLACE)


class APieceThatArrivesLater(unittest.TestCase):
    def test_a_new_piece_does_not_rename_the_case(self):
        """The names already sent to the AI cannot be renumbered."""
        case = Case(name="Lenoir")
        case.add_text("conclusions", CONCLUSIONS)
        case.analyse()
        before = {o.label: o.text for o in case.export()}
        chosen = {row.value: row.pseudonym for row in case.grid.rows}

        case.add_text("mail", MAIL)
        case.analyse()
        after = {row.value: row.pseudonym for row in case.grid.rows}

        for value, pseudonym in chosen.items():
            self.assertEqual(after.get(value), pseudonym, value)
        self.assertEqual({o.label: o.text for o in case.export()}["conclusions"],
                         before["conclusions"])


class TheTableOnDisk(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.case = Case(name="Lenoir c/ Thermopack")
        self.case.add_text("mail", MAIL)
        self.case.analyse()
        self.masked = {o.label: o.text for o in self.case.export()}
        self.path = self.case.save(self.dir / f"lenoir{SUFFIX}")

    def test_the_file_says_what_it_holds_before_anything_else(self):
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(next(iter(payload)), "avertissement")
        self.assertEqual(payload["avertissement"], WARNING)

    def test_the_file_does_not_hold_the_documents(self):
        """A second copy of the case, in a file nobody treats as one."""
        written = self.path.read_text(encoding="utf-8")
        self.assertNotIn("delegue syndical", written)
        self.assertNotIn("convocation", written)

    def test_a_reloaded_case_restores_what_was_sent_out(self):
        reopened = Case.load(self.path)
        outcome = reopened.restore_text(self.masked["mail"])
        self.assertTrue(outcome.ok, outcome.refused)
        self.assertEqual(outcome.text, MAIL)
        self.assertEqual(outcome.unresolved, [])

    def test_a_reloaded_case_still_refuses_a_reworded_pseudonym(self):
        """Per piece, which is the only level the question means anything.

        What each piece consumed is saved with it. Without that, a
        reopened case cannot tell a pseudonym that was reworded from one
        that belonged to another piece, so it stops refusing and reports
        instead, and a half-restored document comes home as a warning
        nobody has to act on.
        """
        from dxanon.case import Case as C

        reopened = C.load(self.path)
        piece = reopened.pieces[0]
        self.assertTrue(piece.used, "what the piece consumed was not saved")

        pseudonym = next(iter(piece.used))
        entry = reopened.table.for_real(pseudonym)
        broken = self.masked["mail"].replace(entry.pseudonym, "Quelquun Dautre")
        outcome = reopened.restore_text(broken, label="mail")
        self.assertFalse(outcome.ok)
        self.assertIn(entry.pseudonym, outcome.refused)

    def test_a_reloaded_case_keeps_its_name_and_its_pieces(self):
        reopened = Case.load(self.path)
        self.assertEqual(reopened.name, "Lenoir c/ Thermopack")
        self.assertEqual([p.label for p in reopened.pieces], ["mail"])

    def test_an_unknown_schema_is_refused_rather_than_guessed(self):
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["schema"] = 99
        other = self.dir / f"futur{SUFFIX}"
        other.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValueError):
            Case.load(other)

    def test_what_fired_is_remembered(self):
        """Lost, a reload refuses a good document over an unused entry."""
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(payload["appliques"])
        self.assertEqual(set(payload["appliques"]), Case.load(self.path).table.used)


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.source = fixtures.build(self.dir / "Dossier_Dupont.docx")
        self.case = Case(name="Dupont")
        self.case.add_file(self.source)
        self.case.add_text("note", "Jean Dupont conteste le licenciement.")
        self.case.analyse()

    def test_a_document_and_a_pasted_note_share_the_table(self):
        rows = {row.value: row for row in self.case.grid.rows}
        self.assertEqual(rows["Jean Dupont"].group, rows["DUPONT"].group)

    def test_the_masked_document_is_written_beside_the_original(self):
        outcomes = self.case.export()
        written = next(o for o in outcomes if o.written is not None)
        self.assertTrue(written.written.exists())
        self.assertNotIn("Dupont", written.written.name)
        self.assertIn("_ANON", written.written.name)

    def test_the_document_comes_back(self):
        written = next(o for o in self.case.export() if o.written is not None)
        outcome = self.case.restore_file(written.written)
        self.assertTrue(outcome.ok, outcome.refused)
        self.assertEqual(text_of(self.source), text_of(outcome.written))

    def test_an_empty_table_is_its_own_answer(self):
        """Not a refusal: a question nobody answered, with its own words."""
        from dxanon.engine import EmptyTable
        from dxanon.workflow import Decision as D

        case = Case(name="Rien")
        case.add_text("note", "Jean Dupont conteste.")
        for row in case.analyse().rows:
            row.decision = D.KEEP
        with self.assertRaises(EmptyTable):
            case.export()

    def test_a_table_nothing_went_out_under_is_not_kept(self):
        """Otherwise the window holds a cycle that produced nothing.

        Closing it would then ask what to do about names no document
        carries, and the next analysis would be told to reuse pseudonyms
        that were never sent anywhere.
        """
        case = Case(name="Refus")
        case.add_file(fixtures.build_with_residue(self.dir / "tout-refuse.docx"))
        case.analyse()
        case.grid.rows.append(_declared("Sylvie Marchand"))
        outcomes = case.export(folder=self.dir / "sortie")
        self.assertFalse(any(o.ok for o in outcomes), [o.refused for o in outcomes])
        self.assertIsNone(case.table)

    def test_a_refused_piece_does_not_stop_the_others(self):
        case = Case(name="Mixte")
        case.add_text("propre", "Jean Dupont conteste.")
        case.add_file(fixtures.build_with_residue(self.dir / "residu.docx"))
        case.analyse()
        # The residue fixture plants a value no detection declares, which
        # is what the refusal check exists for.
        case.grid.rows.append(_declared("Sylvie Marchand"))
        case.analyse_done = True
        outcomes = {o.label: o for o in case.export()}
        self.assertTrue(outcomes["propre"].ok)

    def test_the_images_of_every_piece_are_reported_once(self):
        self.assertEqual(self.case.grid.images, ["word/media/image1.png"])


def _declared(value: str):
    from dxanon.detect import Certainty
    from dxanon.workflow import Row

    return Row(value=value, certainty=Certainty.CERTAIN, why="planté",
               occurrences=1, decision=Decision.REPLACE, kind="name",
               pseudonym="Agnès Nivelle")


if __name__ == "__main__":
    unittest.main()
