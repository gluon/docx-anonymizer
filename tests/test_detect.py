"""Detection: what is arithmetic, what is a guess, and what must be kept."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dxanon import detect  # noqa: E402
from dxanon.detect import Certainty  # noqa: E402

# Reference values, each verified against its own published check digit.
VALID_NIR = "180017500100005"
VALID_IBAN = "FR1420041010050500013M02606"
VALID_SIRET = "73282932000074"
VALID_SIREN = "732829320"


class CheckDigits(unittest.TestCase):
    """No judgement involved: either the arithmetic holds or it does not."""

    def test_nir(self):
        self.assertTrue(detect.nir_is_valid(VALID_NIR))
        self.assertFalse(detect.nir_is_valid("180017500100006"))
        self.assertFalse(detect.nir_is_valid("18001750010000"))

    def test_nir_handles_corsica(self):
        body = "1800175001042"
        corsican = body.replace("75", "2A", 1)
        folded = corsican.replace("2A", "19")
        key = 97 - (int(folded) % 97)
        self.assertTrue(detect.nir_is_valid(f"{corsican}{key:02d}"))

    def test_iban(self):
        self.assertTrue(detect.iban_is_valid(VALID_IBAN))
        self.assertTrue(detect.iban_is_valid("FR76 3000 6000 0112 3456 7890 189"))
        self.assertFalse(detect.iban_is_valid("FR1420041010050500013M02607"))

    def test_siret_and_siren(self):
        self.assertTrue(detect.siret_is_valid(VALID_SIRET))
        self.assertFalse(detect.siret_is_valid("73282932000075"))
        self.assertTrue(detect.siren_is_valid(VALID_SIREN))
        self.assertFalse(detect.siren_is_valid("732829321"))

    def test_la_poste_is_the_documented_exception(self):
        self.assertTrue(detect.siren_is_valid("356000000"))

    def test_a_number_that_is_not_one_is_not_reported(self):
        text = "La facture 123456789012345 et le dossier 999999999 sont joints."
        kinds = {f.kind for f in detect.find(text)}
        self.assertNotIn("nir", kinds)
        self.assertNotIn("siren", kinds)


class FindsInText(unittest.TestCase):
    def test_identifiers_are_certain(self):
        text = f"NIR {VALID_NIR}, IBAN {VALID_IBAN}, contact a.b@example.fr, 06 12 34 56 78."
        findings = {f.kind: f for f in detect.find(text)}
        for kind in ("nir", "iban", "email", "phone"):
            self.assertIn(kind, findings, kind)
            self.assertEqual(findings[kind].certainty, Certainty.CERTAIN)

    def test_a_civility_marks_the_name_after_it(self):
        findings = detect.find("Monsieur Dupont a saisi le conseil.")
        values = {f.value for f in findings}
        self.assertIn("Dupont", values)

    def test_a_company_form_marks_the_name_after_it(self):
        findings = detect.find("La SAS Mecanique Provencale conteste.")
        self.assertTrue(any("Mecanique" in f.value for f in findings))

    def test_declared_values_outrank_guesses(self):
        findings = detect.find("Jean Dupont conteste.", known=["Jean Dupont"])
        declared = [f for f in findings if f.kind == "declared"]
        self.assertEqual(len(declared), 1)
        self.assertEqual(declared[0].certainty, Certainty.CERTAIN)


class OverDetection(unittest.TestCase):
    """Exhaustive by construction: the cost is rows, not missed names."""

    def test_a_capitalised_word_mid_sentence_is_offered(self):
        findings = detect.find("Le salarie a rencontre Vasquez le 3 mars.")
        self.assertIn("Vasquez", {f.value for f in findings})

    def test_a_rare_foreign_surname_is_still_offered(self):
        findings = detect.find("Son collegue Nagyszombathy a confirme.")
        self.assertIn("Nagyszombathy", {f.value for f in findings})

    def test_legal_vocabulary_is_not_offered(self):
        text = "La Cour de Cassation, Chambre Sociale, statuant sur le Licenciement."
        values = {f.value for f in detect.find(text)}
        for word in ("Cour", "Cassation", "Chambre", "Sociale", "Licenciement"):
            self.assertNotIn(word, values, word)

    def test_a_sentence_opener_is_not_offered(self):
        values = {f.value for f in detect.find("Pourtant le salarie conteste.")}
        self.assertNotIn("Pourtant", values)

    def test_a_name_opening_a_sentence_is_still_offered(self):
        """Position is not a filter; it would silence how conclusions read."""
        values = {f.value for f in detect.find("Dupont conteste cette analyse.")}
        self.assertIn("Dupont", values)

    def test_the_known_blind_spot_is_a_name_never_capitalised(self):
        """Stated in the README; pinned here so it stays stated."""
        values = {f.value for f in detect.find("le salarie dupont a saisi")}
        self.assertNotIn("dupont", values)


class CaseLaw(unittest.TestCase):
    """Masking a cited party destroys the citation and the reasoning on it."""

    def test_a_party_to_a_cited_judgment_is_marked_to_keep(self):
        text = "Voir Cass. soc. 25 septembre 2013, Ste Delattre, pourvoi n° 12-12.883."
        findings = {f.value: f for f in detect.find(text)}
        self.assertIn("Delattre", findings)
        self.assertEqual(findings["Delattre"].certainty, Certainty.CASE_LAW)

    def test_the_same_name_outside_a_citation_is_offered_normally(self):
        findings = {f.value: f for f in detect.find("Le temoin Delattre a confirme.")}
        self.assertEqual(findings["Delattre"].certainty, Certainty.CONFIRM)

    def test_a_citation_does_not_shield_the_whole_document(self):
        text = (
            "Cass. soc. 25 septembre 2013, pourvoi n° 12-12.883.\n\n"
            + "Texte neutre. " * 20
            + "Le salarie Vasquez conteste."
        )
        findings = {f.value: f for f in detect.find(text)}
        self.assertEqual(findings["Vasquez"].certainty, Certainty.CONFIRM)


class Grouping(unittest.TestCase):
    def test_a_name_seen_many_times_is_one_row(self):
        text = "Vasquez. " * 40 + "Le salarie Moreau conteste."
        rows = detect.group(detect.find(text))
        values = [row[0] for row in rows]
        self.assertEqual(len(values), len(set(values)))
        counts = {row[0]: row[3] for row in rows}
        self.assertEqual(counts["Vasquez"], 40)

    def test_certain_rows_come_first(self):
        text = f"IBAN {VALID_IBAN}. Le temoin Vasquez a confirme."
        rows = detect.group(detect.find(text))
        self.assertEqual(rows[0][1], Certainty.CERTAIN)


class Identifiers(unittest.TestCase):
    def test_a_birth_date_is_taken_only_where_it_says_so(self):
        taken = {f.value for f in detect.find("né le 12 mars 1978 à Marseille")}
        self.assertIn("12 mars 1978", taken)

        other = {f.value for f in detect.find("Par courrier du 12 mars 1978, il a saisi")}
        self.assertNotIn("12 mars 1978", other)

    def test_an_address_is_taken_whole(self):
        values = {f.value for f in detect.find("demeurant 14 rue des Oliviers, 13005 Marseille")}
        self.assertIn("14 rue des Oliviers", values)
        self.assertIn("13005 Marseille", values)


class MeasuredOnRealisticConclusions(unittest.TestCase):
    """The number that decides whether the tool is usable at all.

    Not a correctness test: a budget. The grid is only workable if a
    two-page pleading yields tens of rows, not hundreds. Pinned so that a
    change to the lexicon or the patterns cannot quietly make the tool
    unusable, in either direction.
    """

    SAMPLE = Path(__file__).resolve().parent / "sample_conclusions.txt"

    def setUp(self):
        self.text = self.SAMPLE.read_text(encoding="utf-8")
        self.rows = detect.group(detect.find(self.text))

    def test_the_grid_stays_within_a_workable_budget(self):
        self.assertLessEqual(len(self.rows), 45, "too many rows to arbitrate")
        self.assertGreaterEqual(len(self.rows), 25, "suspiciously few: check the lexicon")

    def test_every_person_and_company_in_the_file_is_offered(self):
        offered = " ".join(r[0] for r in self.rows if r[1] is not Certainty.CASE_LAW)
        for name in ("DUPONT", "VASQUEZ", "MARCHAND", "BENALI", "ROUX", "FOURNIER",
                     "CHEVALIER", "NGUYEN", "BERNARD", "LAMBERT", "MECANIQUE"):
            self.assertIn(name, offered, f"{name} would have gone out unmasked")

    def test_the_cited_parties_are_kept_and_the_client_is_not(self):
        kept = {r[0] for r in self.rows if r[1] is Certainty.CASE_LAW}
        self.assertEqual(kept, {"Delattre", "Martineau", "Rivoire"})

    def test_identifiers_are_all_certain(self):
        certain = {r[0] for r in self.rows if r[1] is Certainty.CERTAIN}
        for value in ("FR14 2004 1010 0505 0001 3M02 606", "732 829 320",
                      "jean.dupont@mecanique-provencale.fr", "12 mars 1978",
                      "14 rue des Oliviers"):
            self.assertIn(value, certain, value)


if __name__ == "__main__":
    unittest.main()
