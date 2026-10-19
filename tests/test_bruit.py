"""What the grid must not ask, and what it must not miss.

Every case here was found by running the program on a set of conclusions
and a mail thread and reading what came out, not by reasoning about the
code. They are kept together because they share one measure: a row the
reader has to think about costs more than it saves, and a row that is
missing costs everything.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dxanon import detect, plaintext, workflow  # noqa: E402
from dxanon.engine import _occurs  # noqa: E402
from dxanon.mapping import Mapping  # noqa: E402

SAMPLE = (Path(__file__).resolve().parent / "sample_mail_conseil.txt").read_text(encoding="utf-8")


def rows_of(text: str, known: list[str] | None = None) -> dict[str, workflow.Row]:
    return {row.value: row for row in workflow.build(text, known=known).rows}


class LowerCaseSpelling(unittest.TestCase):
    """The leak this pass exists for."""

    def test_a_surname_written_in_lower_case_is_offered(self):
        """"Ensuite, benhaddou a envoyé" went out in clear.

        Nothing vouched for "Karim Benhaddou": no civility, no company
        form, no declaration, so it was a bare candidate and its other
        spellings were never searched for. A capitalised run of two words
        now vouches for itself.
        """
        rows = rows_of("Le courriel de Karim Benhaddou le dit. Ensuite, benhaddou a confirme.")
        self.assertIn("benhaddou", rows)
        self.assertIs(rows["benhaddou"].decision, workflow.Decision.REPLACE)

    def test_a_single_capitalised_word_still_vouches_for_nothing(self):
        """The regression that bounded the rule: "bulletins de paie"."""
        rows = rows_of("Le Bulletin indique le montant. Les bulletins de paie sont joints.")
        self.assertNotIn("bulletins", rows)

    def test_the_lower_case_spelling_is_the_same_subject(self):
        grid = workflow.build("Mandatee par Karim Benhaddou. Ensuite, benhaddou a repondu.")
        rows = {r.value: r for r in grid.rows}
        self.assertEqual(rows["benhaddou"].group, rows["Karim Benhaddou"].group)
        self.assertEqual(
            rows["benhaddou"].pseudonym,
            rows["Karim Benhaddou"].pseudonym.split()[-1].lower(),
        )


class WhatTheGridMustNotAsk(unittest.TestCase):
    def test_abbreviated_civilities_are_not_first_names(self):
        """"Mme Lenoir" was masked as "Romain Mercier"."""
        rows = rows_of("La convocation de Mme Lenoir est du 2 juin.")
        self.assertNotIn("Mme", rows)
        self.assertNotIn("Mme Lenoir", rows)
        self.assertIn("Lenoir", rows)

    def test_table_headings_and_job_titles_are_not_offered(self):
        text = ("Chef de demande. Fondement. Montant. Dommages-interets, execution "
                "deloyale. Article 700 CPC. Attestation Pole emploi. "
                "Assistante juridique. Avocate au barreau.")
        for noise in ("Chef", "Fondement", "Montant", "Dommages-interets", "CPC",
                      "Pole", "Assistante", "Avocate"):
            self.assertNotIn(noise, rows_of(text), noise)

    def test_a_question_opening_a_sentence_is_not_a_name(self):
        """"Pouvez-vous verifier" came back as "Sabine verifier"."""
        self.assertNotIn("Pouvez-vous", rows_of("Pouvez-vous verifier la portabilite ?"))

    def test_a_generic_trade_word_alone_is_not_a_name(self):
        """"Section Industrie" is the court's section, not a company."""
        rows = rows_of("Section Industrie - RG n° F 25/00412")
        self.assertNotIn("Industrie", rows)
        self.assertEqual(rows, {})

    def test_the_company_is_still_caught_when_the_word_is_part_of_its_name(self):
        rows = rows_of("La SAS THERMOPACK INDUSTRIE conteste.")
        self.assertTrue(any("THERMOPACK" in value for value in rows), rows)


class References(unittest.TestCase):
    def test_a_file_reference_is_an_identifier_not_a_name(self):
        """"AL-2025-77412" used to surface as the name "AL"."""
        rows = rows_of("Leur reference dossier est AL-2025-77412.")
        self.assertIn("AL-2025-77412", rows)
        self.assertNotIn("AL", rows)
        self.assertEqual(rows["AL-2025-77412"].pseudonym, "[référence 1]")

    def test_a_staff_number_is_an_identifier(self):
        rows = rows_of("Son matricule interne est le 4471-C.")
        self.assertIn("4471-C", rows)
        self.assertFalse(rows["4471-C"].is_person_like)

    def test_an_article_of_the_code_is_not_a_reference(self):
        self.assertNotIn("1235-3-1", rows_of("au visa de l'article L. 1235-3-1 du code du travail"))


class Addresses(unittest.TestCase):
    def test_the_closing_full_stop_is_not_part_of_the_address(self):
        rows = rows_of("Je serai au cabinet lundi, 14 rue Edouard Delanglade.")
        self.assertIn("14 rue Edouard Delanglade", rows)

    def test_the_town_keeps_its_own_row(self):
        """The town was swallowed into the street line and lost its row."""
        rows = rows_of("Le siege est 8 chemin de la Nerthe a Marseille, dans le 16e.")
        self.assertIn("8 chemin de la Nerthe", rows)
        self.assertIn("Marseille", rows)

    def test_a_postcode_line_keeps_its_town(self):
        """The opposite rule, and the reason the trimming is not global."""
        self.assertIn("13005 Marseille", rows_of("demeurant 27 boulevard Chave, 13005 Marseille"))


class CitedJudgments(unittest.TestCase):
    def test_a_party_named_before_a_bracketed_citation_is_kept(self):
        """One form was kept and the other masked, in the same paragraph."""
        text = ("La Cour a retenu cette solution dans l'affaire Societe Bergerat Monnoyeur "
                "(Cass. soc., 25 septembre 2019, n° 17-31.171). Elle l'a confirmee.")
        rows = rows_of(text)
        self.assertIs(rows["Bergerat Monnoyeur"].decision, workflow.Decision.KEEP)

    def test_the_client_is_not_shielded_by_a_citation_in_the_same_sentence(self):
        text = ("Madame Lenoir invoque l'arret (Cass. soc., 8 juillet 2020). "
                "Madame Lenoir a ete licenciee le 19 juin.")
        self.assertIs(rows_of(text)["Lenoir"].decision, workflow.Decision.REPLACE)


class OnePersonOneName(unittest.TestCase):
    def test_a_first_name_and_a_surname_are_joined_by_the_address(self):
        """A mail writes "Sophie" in one line and "Mme Lenoir" in another.

        No row contains the other, so the grouping by words saw two
        people and invented two names for one woman.
        """
        text = ("Sophie a recu la convocation. La situation de Mme Lenoir est claire. "
                "Elle ecrit depuis sophie.lenoir@orange.fr.")
        grid = workflow.build(text)
        rows = {r.value: r for r in grid.rows}
        self.assertEqual(rows["Sophie"].group, rows["Lenoir"].group)
        self.assertNotEqual(rows["Sophie"].pseudonym, rows["Lenoir"].pseudonym)

    def test_a_shared_mailbox_joins_nobody(self):
        """Merging two partners of a firm would be worse than the split."""
        text = ("Maitre Dupont et Maitre Martin repondent. "
                "Ecrire a cabinet.dupont.martin@exemple.fr.")
        grid = workflow.build(text)
        rows = {r.value: r for r in grid.rows}
        self.assertNotEqual(rows["Dupont"].group, rows["Martin"].group)

    def test_no_pseudonym_carries_a_number(self):
        """"le licenciement de Madame LEMOINE 2", in a set of conclusions.

        The suffix was a collision between two spellings of one subject,
        because each spelling reserved its own words as it was rendered.
        """
        for row in workflow.build(SAMPLE).rows:
            self.assertNotRegex(row.pseudonym, r"\s\d+$", row.value)


class WordBoundaries(unittest.TestCase):
    """A clean export was refused over a word that was not a name."""

    def test_a_value_inside_a_longer_word_is_not_an_occurrence(self):
        self.assertFalse(_occurs("Industrie", "La SAS Orion Industries conteste"))

    def test_the_value_itself_still_is(self):
        self.assertTrue(_occurs("Industrie", "La SAS Orion Industrie conteste"))
        self.assertTrue(_occurs("Dupont", "signe M.DUPONT? non: Dupont."))

    def test_the_table_check_agrees_with_the_export_check(self):
        """Both said no to the same document, on the same non-name.

        The table warned that "Orion Industries" held "Industrie", and
        the export then refused for the same reason. Neither was a leak:
        the masked text reads "Orion Industries", which is the invented
        company, and the word "Industrie" left in it names the court's
        section.
        """
        text = "la SAS Thermopack Industrie, Section Industrie"
        mapping = Mapping()
        mapping.add("Thermopack Industrie", "Orion Industries")
        mapping.add("Industrie", "Secteur")

        self.assertEqual(mapping.conflicts(), [])
        masked = plaintext.anonymize(text, mapping)
        self.assertEqual(masked, "la SAS Orion Industries, Section Secteur")

    def test_a_pseudonym_still_showing_its_own_real_value_is_refused(self):
        """The limit of the boundary rule: a real occurrence still fires."""
        from dxanon.engine import RefusedExport

        mapping = Mapping()
        mapping.add("Industrie", "Industrie et Fils")
        with self.assertRaises(RefusedExport):
            plaintext.anonymize("Section Industrie", mapping)


class MeasuredOnTheSample(unittest.TestCase):
    """The budget, on a real 436-word thread.

    Twelve rows of it were noise before this pass, and one real name was
    missed entirely. The numbers are pinned so a future change to the
    lexicons cannot quietly undo it.
    """

    def setUp(self):
        self.grid = workflow.build(SAMPLE)
        self.rows = {row.value: row for row in self.grid.rows}

    def test_the_grid_stays_under_its_budget(self):
        self.assertLessEqual(len(self.grid.rows), 32, sorted(self.rows))

    def test_nobody_is_missed(self):
        for name in ("Lenoir", "Karim Benhaddou", "Helene Vasseur", "Thomas Reybaud",
                     "Patrick Senechal", "Alain Peyrolles", "Nadia Belkacem",
                     "Claire Fontanel", "Alteor", "Thermopack", "benhaddou"):
            self.assertIn(name, self.rows)

    def test_the_table_is_coherent_as_built(self):
        self.assertEqual(self.grid.conflicts(), [])

    def test_the_masked_text_holds_no_real_name(self):
        masked = plaintext.anonymize(SAMPLE, self.grid.to_mapping())
        for name in ("Lenoir", "LENOIR", "lenoir", "Sophie", "Benhaddou", "benhaddou",
                     "Vasseur", "Reybaud", "Senechal", "Peyrolles", "Belkacem",
                     "Fontanel", "Thermopack", "Alteor", "orange.fr", "FR17", "417 893"):
            self.assertNotIn(name, masked, name)

    def test_the_round_trip_is_exact(self):
        mapping = self.grid.to_mapping()
        restored, missing = plaintext.deanonymize(plaintext.anonymize(SAMPLE, mapping), mapping)
        self.assertEqual(restored, SAMPLE)
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
