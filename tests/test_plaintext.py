"""Pasted text and sessions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dxanon import plaintext  # noqa: E402
from dxanon.engine import EmptyTable, RefusedExport  # noqa: E402
from dxanon.mapping import Mapping  # noqa: E402


def mapping() -> Mapping:
    m = Mapping()
    m.add("Jean Dupont", "Marc Lemoine")
    m.add("Dupont", "Lemoine")
    m.add("Mecanique Provencale", "Orion")
    return m


class PastedText(unittest.TestCase):
    def test_round_trip_returns_the_original(self):
        m = mapping()
        source = "Jean Dupont travaille chez Mecanique Provencale. Dupont conteste."
        masked = plaintext.anonymize(source, m)
        self.assertNotIn("Dupont", masked)
        restored, missing = plaintext.deanonymize(masked, m)
        self.assertEqual(restored, source)
        self.assertEqual(missing, [])

    def test_a_longer_name_wins_over_the_surname_inside_it(self):
        masked = plaintext.anonymize("Jean Dupont et Dupont", mapping())
        self.assertEqual(masked, "Marc Lemoine et Lemoine")

    def test_a_replacement_is_never_replaced_again(self):
        """The silent double rename, pinned at the substitution itself.

        Chaining str.replace over the pairs would turn "Jean Dupont" into
        "Patrick Lemoine" here: wrong, and no longer restorable, because
        the table has no entry for what was actually written.
        """
        pairs = [("Jean Dupont", "Marc Lemoine"), ("Marc", "Patrick")]
        self.assertEqual(
            plaintext._replace("Jean Dupont a vu Marc.", pairs),
            "Marc Lemoine a vu Patrick.",
        )

    def test_a_pseudonym_holding_another_real_value_is_refused(self):
        """The table above is incoherent, and the export says so."""
        m = Mapping()
        m.add("Jean Dupont", "Marc Lemoine")
        m.add("Marc", "Patrick")

        self.assertTrue(m.conflicts())
        with self.assertRaises(RefusedExport):
            plaintext.anonymize("Jean Dupont a vu Marc.", m)

    def test_a_clean_table_reports_no_conflict(self):
        self.assertEqual(mapping().conflicts(), [])

    def test_a_pseudonym_equal_to_another_real_value_is_a_conflict(self):
        m = Mapping()
        m.add("Dupont", "Moreau")
        m.add("Moreau", "Lemoine")
        self.assertTrue(m.conflicts())

    def test_an_empty_table_refuses(self):
        with self.assertRaises(EmptyTable):
            plaintext.anonymize("Monsieur Dupont", Mapping())

    def test_a_surviving_real_value_refuses(self):
        m = Mapping()
        m.add("Dupont", "Dupont-bis")  # the pseudonym contains the real value
        with self.assertRaises(RefusedExport):
            plaintext.anonymize("Monsieur Dupont", m)

    def test_a_reworded_pseudonym_blocks_the_return(self):
        m = mapping()
        masked = plaintext.anonymize("Jean Dupont conteste.", m)
        broken = masked.replace("Marc Lemoine", "Marc Lemoyne")
        with self.assertRaises(RefusedExport):
            plaintext.deanonymize(broken, m)

    def test_an_extract_can_come_back_when_gaps_are_expected(self):
        m = mapping()
        restored, missing = plaintext.deanonymize("Orion conteste.", m, require_all=False)
        self.assertEqual(restored, "Mecanique Provencale conteste.")
        self.assertIn("Marc Lemoine", missing)


class Pseudonyms(unittest.TestCase):
    def test_a_generated_pseudonym_avoids_the_source_text(self):
        """A name already in the document cannot be undone afterwards."""
        from dxanon.mapping import propose

        text = "Le temoin Lemoine et Marc Riviere ont confirme."
        taken: set[str] = set()
        for _ in range(8):
            candidate = propose("name", taken, text=text)
            for part in candidate.split():
                self.assertNotIn(part.lower(), text.lower(), candidate)
            taken.add(candidate)

    def test_accents_are_not_a_disguise(self):
        from dxanon.mapping import propose

        candidate = propose("name", set(), text="Marc Riviere a confirme.")
        self.assertNotIn("Rivi", candidate)
        self.assertNotIn("Marc", candidate)

    def test_generated_names_do_not_all_share_a_surname(self):
        from dxanon.mapping import propose

        taken: set[str] = set()
        for _ in range(8):
            taken.add(propose("name", taken))
        surnames = {name.split()[-1] for name in taken}
        self.assertGreater(len(surnames), 3, taken)



if __name__ == "__main__":
    unittest.main()
