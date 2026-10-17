"""The grid's decisions, tested without a window."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dxanon import plaintext, workflow  # noqa: E402
from dxanon.detect import Certainty  # noqa: E402
from dxanon.workflow import Decision  # noqa: E402

SAMPLE = Path(__file__).resolve().parent / "sample_conclusions.txt"


class Defaults(unittest.TestCase):
    def test_an_uncertain_row_is_masked_unless_told_otherwise(self):
        """Over-masking is noticed; under-masking is not."""
        grid = workflow.build("Le temoin Vasquez a confirme.")
        row = next(r for r in grid.rows if r.value == "Vasquez")
        self.assertEqual(row.certainty, Certainty.CONFIRM)
        self.assertEqual(row.decision, Decision.REPLACE)

    def test_a_cited_party_is_kept(self):
        text = "Cass. soc. 25 septembre 2013, Societe Delattre, pourvoi n° 12-12.883."
        grid = workflow.build(text)
        row = next(r for r in grid.rows if r.value == "Delattre")
        self.assertEqual(row.decision, Decision.KEEP)
        self.assertEqual(row.pseudonym, "")

    def test_a_kept_row_never_reaches_the_table(self):
        text = "Cass. soc. 25 septembre 2013, Societe Delattre, pourvoi n° 12-12.883."
        mapping = workflow.build(text).to_mapping()
        self.assertIsNone(mapping.for_real("Delattre"))


class OnePersonOnePseudonym(unittest.TestCase):
    """Three spellings of one man must not become three men."""

    TEXT = (
        "Monsieur Jean DUPONT a saisi le conseil. DUPONT soutient que "
        "l'employeur a manque. Dupont produit ses pieces."
    )

    def setUp(self):
        self.grid = workflow.build(self.TEXT)
        self.rows = {r.value: r for r in self.grid.rows}

    def test_every_spelling_shares_one_surname(self):
        surnames = {
            self.rows[v].pseudonym.split()[-1].upper()
            for v in ("Jean DUPONT", "DUPONT", "Dupont")
            if v in self.rows
        }
        self.assertEqual(len(surnames), 1, self.rows)

    def test_the_shape_and_case_of_each_spelling_is_matched(self):
        self.assertTrue(self.rows["DUPONT"].pseudonym.isupper())
        self.assertFalse(self.rows["Dupont"].pseudonym.isupper())
        self.assertEqual(len(self.rows["Jean DUPONT"].pseudonym.split()), 2)

    def test_the_masked_text_reads_consistently(self):
        masked = plaintext.anonymize(self.TEXT, self.grid.to_mapping())
        self.assertNotIn("DUPONT", masked)
        self.assertNotIn("Dupont", masked)
        surname = self.rows["DUPONT"].pseudonym
        self.assertIn(surname, masked)

    def test_the_round_trip_still_returns_the_original(self):
        mapping = self.grid.to_mapping()
        masked = plaintext.anonymize(self.TEXT, mapping)
        restored, missing = plaintext.deanonymize(masked, mapping)
        self.assertEqual(restored, self.TEXT)
        self.assertEqual(missing, [])


class Identifiers(unittest.TestCase):
    def test_an_identifier_is_replaced_by_a_visible_placeholder(self):
        grid = workflow.build("IBAN FR14 2004 1010 0505 0001 3M02 606 et 06 12 34 56 78.")
        placeholders = [r.pseudonym for r in grid.rows if r.certainty is Certainty.CERTAIN]
        self.assertTrue(placeholders)
        for value in placeholders:
            self.assertTrue(value.startswith("[") or "@" in value, value)

    def test_every_pseudonym_is_unique(self):
        """A correctness requirement, not tidiness.

        Two real values sharing one pseudonym cannot be told apart on the
        way back: the document comes home with one of them in both
        places, silently.
        """
        grid = workflow.build(SAMPLE.read_text(encoding="utf-8"))
        pseudonyms = [r.pseudonym for r in grid.rows if r.decision is Decision.REPLACE]
        self.assertEqual(len(pseudonyms), len(set(pseudonyms)))

    def test_a_mistyped_number_gets_a_placeholder_not_a_name(self):
        """Judged on the kind, never on the certainty.

        A social security number whose check digit fails drops to
        "confirm". Judging by certainty gave it a person's pseudonym and
        produced "numéro de sécurité sociale Altaïr" in the masked text.
        """
        text = "numéro de sécurité sociale 1 78 03 13 055 123 42, demandeur"
        grid = workflow.build(text)
        row = next(r for r in grid.rows if r.value.startswith("1 78"))
        self.assertTrue(row.pseudonym.startswith("["), row.pseudonym)

    def test_context_decides_person_company_or_town(self):
        text = (
            "Monsieur Vasquez, domicilié à Sainteville, employé par la SAS Trameco, "
            "assisté de Madame Lenoir."
        )
        grid = workflow.build(text)
        rows = {r.value: r for r in grid.rows}
        self.assertEqual(len(rows["Sainteville"].pseudonym.split()), 1)
        self.assertEqual(len(rows["Vasquez"].pseudonym.split()), 1)
        masked = plaintext.anonymize(text, grid.to_mapping())
        self.assertNotIn("Vasquez", masked)
        self.assertNotIn("Sainteville", masked)
        self.assertNotIn("Trameco", masked)

    def test_placeholders_say_what_was_removed(self):
        grid = workflow.build("né le 12 mars 1978, demeurant 14 rue des Oliviers")
        labels = {r.pseudonym for r in grid.rows if r.certainty is Certainty.CERTAIN}
        self.assertTrue(any("date de naissance" in v for v in labels), labels)
        self.assertTrue(any("adresse" in v for v in labels), labels)

    def test_an_email_is_replaced_by_an_unusable_address(self):
        grid = workflow.build("Contact : jean.dupont@example.fr")
        row = next(r for r in grid.rows if "@" in r.value)
        self.assertTrue(row.pseudonym.endswith(".invalid"))


class OnTheRealisticSample(unittest.TestCase):
    def setUp(self):
        self.text = SAMPLE.read_text(encoding="utf-8")
        self.grid = workflow.build(self.text)

    def test_the_table_it_produces_is_coherent(self):
        self.assertEqual(self.grid.conflicts(), [])

    def test_no_pseudonym_already_occurs_in_the_source(self):
        for row in self.grid.rows:
            if row.decision is Decision.REPLACE and row.is_person_like:
                for part in row.pseudonym.split():
                    self.assertNotIn(part, self.text, row.pseudonym)

    def test_the_whole_document_round_trips(self):
        mapping = self.grid.to_mapping()
        masked = plaintext.anonymize(self.text, mapping)
        restored, missing = plaintext.deanonymize(masked, mapping)
        self.assertEqual(restored, self.text)
        self.assertEqual(missing, [])

    def test_the_client_name_is_gone_from_the_masked_text(self):
        masked = plaintext.anonymize(self.text, self.grid.to_mapping())
        for name in ("DUPONT", "Dupont", "VASQUEZ", "MARCHAND", "BENALI"):
            self.assertNotIn(name, masked, name)

    def test_the_cited_parties_survive_masking(self):
        masked = plaintext.anonymize(self.text, self.grid.to_mapping())
        for party in ("Delattre", "Martineau", "Rivoire"):
            self.assertIn(party, masked, party)



class PseudonymsMustNotOverlap(unittest.TestCase):
    """No subject may be given a word of another subject's pseudonym.

    "Camille" was given "Bruno" while another person was given "Bruno
    Delacroix". The restoration replaces the longer first, so the full
    text round-trips fine and the defect stays hidden, until a model
    shortens "Bruno Delacroix" to "le Docteur Bruno" and the document
    comes home naming the wrong person. There is nothing to notice it
    with, which is what makes it worth a test.
    """

    def setUp(self):
        self.text = SAMPLE.read_text(encoding="utf-8")
        self.grid = workflow.build(self.text)

    def test_no_pseudonym_is_a_word_of_another_subject(self):
        by_group: dict[str, set[str]] = {}
        for row in self.grid.rows:
            if row.decision is Decision.REPLACE and row.is_person_like:
                by_group.setdefault(row.group, set()).update(row.pseudonym.split())

        for group, words in by_group.items():
            for other, other_words in by_group.items():
                if group == other:
                    continue
                shared = words & other_words
                self.assertFalse(shared, f"{group} and {other} share {shared}")

    def test_a_shortened_pseudonym_cannot_restore_as_someone_else(self):
        """The failure the rule above prevents, played out."""
        mapping = self.grid.to_mapping()
        two_word = [e for e in mapping.entries if len(e.pseudonym.split()) == 2]

        for entry in two_word[:6]:
            shortened = entry.pseudonym.split()[-1]
            match = mapping.for_pseudonym(shortened)
            if match is not None:
                self.assertEqual(
                    match.real.split()[-1], entry.real.split()[-1],
                    f"{shortened} restores to {match.real}, not to {entry.real}",
                )


if __name__ == "__main__":
    unittest.main()
