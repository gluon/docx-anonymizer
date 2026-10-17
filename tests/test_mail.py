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

    def test_a_name_written_in_lower_case_is_caught(self):
        """The leak this fixture found, now closed.

        "priver benzaoui des trajets" sits in the mail in lower case.
        Every detection rule starts from a capital letter, so it was
        invisible to all of them and the client's real name went out in
        the masked copy. Once a name has been found in any spelling its
        other spellings are searchable, so this one is offered, grouped
        with its own person, and masked in the matching case.
        """
        row = self.rows["benzaoui"]
        self.assertEqual(row.decision, Decision.REPLACE)
        self.assertEqual(row.group, self.rows["Rachid BENZAOUI"].group)
        self.assertTrue(row.pseudonym.islower(), row.pseudonym)

        masked = plaintext.anonymize(self.text, self.grid.to_mapping())
        self.assertNotIn("benzaoui", masked)

    def test_that_search_does_not_reach_ordinary_words(self):
        """The risk the fix carries, bounded.

        A surname can also be a common noun. The search only runs on
        names something in the sentence vouched for: a civility, a
        company form, or the user's declaration. Searching every
        capitalised candidate instead made "Bulletin", kept as a
        case-law marker, a reason to mask "bulletins de paie".
        """
        self.assertIn("bulletins de paie", self.text)
        self.assertNotIn("bulletin", self.rows)

        masked = plaintext.anonymize(self.text, self.grid.to_mapping())
        self.assertIn("bulletins de paie", masked)


class AfterTheAIRewroteIt(unittest.TestCase):
    """The round trip on a text that has actually been rewritten.

    Every other round-trip test restores a document nobody touched,
    which is the easy case. Here the masked text is put through the kind
    of edit an AI makes when asked to rework a mail: paragraphs
    reordered, sentences dropped, connectives swapped, headings added.
    The pseudonyms are left alone, as a model reasoning about the text
    leaves proper nouns alone, and the real names must come back.

    The rewrite is generated rather than stored. A recorded one freezes
    the pseudonyms of the day it was made, so adding a single detection
    rule renames everything and the test fails for a reason that has
    nothing to do with what it checks.
    """

    def setUp(self):
        self.text = MAIL.read_text(encoding="utf-8")
        self.mapping = workflow.build(self.text).to_mapping()
        self.masked = plaintext.anonymize(self.text, self.mapping)
        self.reworked = _rewrite(self.masked)

    def test_the_rewrite_really_changed_the_text(self):
        """Otherwise the test below proves nothing."""
        self.assertNotEqual(self.reworked, self.masked)
        self.assertLess(len(self.reworked.split()), len(self.masked.split()))

    def test_the_real_names_come_back(self):
        restored, missing = plaintext.deanonymize(self.reworked, self.mapping,
                                                  require_all=False)

        # The rewrite drops whole paragraphs, so some pseudonyms are
        # legitimately gone. What must hold is that the ones reported
        # missing are exactly the ones the rewrite removed, and no other.
        for pseudonym in missing:
            self.assertNotIn(pseudonym, self.reworked, pseudonym)

        for entry in self.mapping.entries:
            if entry.pseudonym and entry.pseudonym in self.reworked:
                self.assertIn(entry.real, restored, entry.real)

    def test_no_pseudonym_is_left_in_the_restored_text(self):
        restored, _ = plaintext.deanonymize(self.reworked, self.mapping,
                                            require_all=False)
        for entry in self.mapping.entries:
            if entry.pseudonym and entry.pseudonym in self.reworked:
                self.assertNotIn(entry.pseudonym, restored, entry.pseudonym)

    def test_the_cited_parties_survive_the_whole_trip(self):
        restored, _ = plaintext.deanonymize(self.reworked, self.mapping,
                                            require_all=False)
        for party in ("Dufaure", "Lemarchand", "Bergeron Logistique"):
            self.assertIn(party, restored, party)

    def test_a_reworded_pseudonym_is_refused_rather_than_half_restored(self):
        """What must happen when the model does not leave a name alone."""
        from dxanon.engine import RefusedExport

        target = next(e for e in self.mapping.entries
                      if e.pseudonym and e.pseudonym in self.reworked
                      and len(e.pseudonym) > 6)
        broken = self.reworked.replace(target.pseudonym, target.pseudonym[:-1] + "z")

        with self.assertRaises(RefusedExport):
            plaintext.deanonymize(broken, self.mapping)


def _rewrite(text: str) -> str:
    """Edit a text the way a model asked to rework it would.

    Drops a sixth of the sentences, swaps connectives, and reorders the
    paragraphs of the body, while never touching a capitalised word, a
    bracketed placeholder or an address: that is what a model does when
    it rewrites prose and reasons about the names rather than renaming
    them.
    """
    swaps = {
        "Je reviens vers vous": "Je reviens vers vous à présent",
        "Pour mémoire": "Rappel",
        "Ce que je n'avais pas": "Ce dont je ne disposais pas",
        "Sur le fond": "Au fond",
        "Je précise": "Je souligne",
        "Le risque": "La difficulté",
        "Premièrement": "D'abord",
        "Deuxièmement": "Ensuite",
        "Troisièmement": "Enfin",
    }
    for old, new in swaps.items():
        text = text.replace(old, new)

    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    kept = [p for index, p in enumerate(paragraphs) if index % 6 != 4]
    head, body, tail = kept[:3], kept[3:-4], kept[-4:]
    return "\n\n".join(head + body[::-1] + tail)



if __name__ == "__main__":
    unittest.main()
