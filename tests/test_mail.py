"""The mail fixture, and the five defects it exposed.

A thousand-word confraternal exchange broke the grid in ways two pages
of conclusions never did: a letter is mostly greeting and sign-off, a
company is named in full once and in shorthand afterwards, and a
signature block puts a town and a firm on consecutive lines.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dxanon import plaintext, workflow  # noqa: E402
from dxanon.detect import Certainty  # noqa: E402
from dxanon.workflow import Decision  # noqa: E402

MAIL = Path(__file__).resolve().parent / "sample_mail.txt"


class TheMail(unittest.TestCase):
    def setUp(self):
        self.text = MAIL.read_text(encoding="utf-8")
        self.grid = workflow.build(self.text)
        self.rows = {r.value: r for r in self.grid.rows}

    # -- the five defects -------------------------------------------------

    def test_a_run_never_crosses_a_line_break(self):
        """A signature block is not one long name.

        "Barreau de Marseille\\nCabinet Moreau" came out as the single
        value "Marseille Cabinet Moreau", and the address pattern ate
        the "Tél" on the line below a postcode.
        """
        for value in self.rows:
            self.assertNotIn("\n", value, repr(value))
        self.assertNotIn("Marseille Cabinet Moreau", self.rows)

    def test_the_furniture_of_a_letter_is_not_offered_as_a_name(self):
        for word in ("Merci", "Chère Consoeur", "Confraternellement",
                     "Dites-moi", "Trois", "Situation", "RE", "Associés"):
            self.assertNotIn(word, self.rows, word)

    def test_a_company_named_three_ways_is_one_company(self):
        """It split into three unrelated pseudonyms before.

        The old key was the last word alone, so "TRANSPORTS
        FRIGORIFIQUES DU LITTORAL" and "Transports Frigorifiques" landed
        in different groups.
        """
        full = self.rows["TRANSPORTS FRIGORIFIQUES DU LITTORAL"]
        short = self.rows["Transports Frigorifiques"]
        self.assertEqual(full.group, short.group)
        self.assertEqual(
            full.pseudonym.split()[0].upper(), short.pseudonym.split()[0].upper()
        )

    def test_a_bare_first_name_joins_its_own_person(self):
        self.assertEqual(self.rows["Sylvain"].group, self.rows["Sylvain Grandclément"].group)
        self.assertIn(
            self.rows["Sylvain"].pseudonym, self.rows["Sylvain Grandclément"].pseudonym
        )

    def test_a_company_does_not_get_a_person_name(self):
        """One explicit "la société X" outweighs any number of silent mentions."""
        full = self.rows["TRANSPORTS FRIGORIFIQUES DU LITTORAL"].pseudonym
        self.assertGreater(len(full.split()), 1, full)
        self.assertNotIn(full.split()[0].title(), ("Marc", "Claire", "Fabrice", "Nadia"))

    # -- what the output has to read like ---------------------------------

    def test_an_initialism_stays_an_initialism(self):
        """"son compte FABRICE" stops a reader cold."""
        pseudonym = self.rows["BNP"].pseudonym
        self.assertTrue(pseudonym.isupper() and pseudonym.isalpha(), pseudonym)
        self.assertLessEqual(len(pseudonym), 5)

    def test_a_place_gets_a_place_name(self):
        self.assertTrue(self.rows["Saint-Menet"].pseudonym.lower().startswith("saint"))
        self.assertEqual(len(self.rows["Oran"].pseudonym.split()), 1)

    # -- the properties that must hold whatever the text ------------------

    def test_the_round_trip_is_exact(self):
        mapping = self.grid.to_mapping()
        masked = plaintext.anonymize(self.text, mapping)
        restored, missing = plaintext.deanonymize(masked, mapping)
        self.assertEqual(restored, self.text)
        self.assertEqual(missing, [])

    def test_every_pseudonym_is_distinct(self):
        """Two subjects sharing one pseudonym cannot be told apart on the way back."""
        used = [r.pseudonym for r in self.grid.rows if r.decision is Decision.REPLACE]
        self.assertEqual(len(used), len(set(used)))

    def test_the_table_is_coherent(self):
        self.assertEqual(self.grid.conflicts(), [])

    def test_everyone_in_the_file_is_offered(self):
        offered = " ".join(r[0] for r in [(r.value,) for r in self.grid.rows])
        for name in ("Benzaoui", "Lahmar", "Vandenbroucke", "Vasseur", "Pereira-Lemonnier",
                     "Aubert-Nguyen", "Diakité", "Tabarly", "Grandclément", "Moreau"):
            self.assertIn(name, offered, f"{name} would have gone out unmasked")

    def test_the_cited_parties_are_kept(self):
        kept = {r.value for r in self.grid.rows if r.certainty is Certainty.CASE_LAW}
        for party in ("Dufaure", "Lemarchand", "Bergeron Logistique"):
            self.assertIn(party, kept, party)

    def test_the_homonym_colleague_is_still_masked(self):
        """A client must not be shielded by sharing a name with a cited party."""
        self.assertEqual(self.rows["Vasseur"].decision, Decision.REPLACE)

    def test_the_grid_stays_within_a_workable_budget(self):
        self.assertLessEqual(len(self.grid.rows), 50, "too many rows to arbitrate")

    def test_the_known_blind_spot_is_still_there(self):
        """Stated in the README, visible here in real conditions.

        "priver benzaoui des trajets" is in the mail, in lower case, and
        no local method offers it. Pinned so the claim stays honest.
        """
        self.assertIn("benzaoui des trajets", self.text)
        self.assertNotIn("benzaoui", self.rows)


if __name__ == "__main__":
    unittest.main()
