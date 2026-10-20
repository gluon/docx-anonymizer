"""Finding what needs masking, locally and without a model.

Three layers, in decreasing order of certainty:

  * **Check-digit formats.** A French social security number, an IBAN and
    a SIRET each carry an arithmetic check. Either the arithmetic holds or
    the string is not one. There is no judgement involved and no false
    positive to arbitrate.
  * **Declared names and their spellings.** Generated from what the user
    typed, never guessed from the document.
  * **Over-detection.** Rather than trying to recognise names, the engine
    eliminates what cannot be one: sentence openers, known legal
    vocabulary, ordinary French words. Whatever is left is *offered* as a
    candidate. Exhaustive by construction for capitalised names; the cost
    is rows to arbitrate, not missed names.

One class of name must be *kept*: parties to a cited judgment. Masking
the name in `Cass. soc. 25 septembre 2013, Sté Dupont` destroys the
citation and the reasoning that rests on it. Those are public names with
no connection to the client.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


class Certainty(str, Enum):
    CERTAIN = "certain"        # arithmetic or a closed format: replace by default
    CONFIRM = "confirm"        # looks like a proper noun: the user decides
    CASE_LAW = "case_law"      # party to a cited judgment: keep by default


@dataclass(frozen=True)
class Finding:
    value: str
    start: int
    end: int
    kind: str
    certainty: Certainty
    why: str


# --------------------------------------------------------------------------
# Check-digit formats
# --------------------------------------------------------------------------

NIR = re.compile(r"\b([12])[\s.]?(\d{2})[\s.]?(0[1-9]|1[0-2]|[2-9]\d)[\s.]?(\d{2}|2[AB])[\s.]?(\d{3})[\s.]?(\d{3})[\s.]?(\d{2})\b", re.IGNORECASE)
IBAN = re.compile(r"\b([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?)\b")
SIRET = re.compile(r"\b(\d{3}[ .]?\d{3}[ .]?\d{3}[ .]?\d{5})\b")
SIREN = re.compile(r"\b(\d{3}[ .]?\d{3}[ .]?\d{3})\b")
EMAIL = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PHONE_FR = re.compile(r"(?:\+33[\s.-]?|\b0)[1-9](?:[\s.-]?\d{2}){4}\b")
PLATE = re.compile(r"\b[A-Z]{2}-\d{3}-[A-Z]{2}\b")

#: A file or staff reference: letters and digits joined by hyphens, in
#: either order. ``AL-2025-77412`` and ``4471-C`` identify a person as
#: surely as a name does, and both used to surface as a bare capitalised
#: fragment ("AL") that the grid could only read as a name.
REFERENCE = re.compile(r"\b(?:[A-Z]{1,5}-\d{2,8}(?:-\d{1,8})*|\d{3,8}-[A-Z]{1,4})\b")

#: A date of birth, taken only where its context says that is what it is.
#: Dates are everywhere in a case file; detecting them all would bury the
#: grid, so only the ones announced as a birth date are reported.
BIRTH_DATE = re.compile(
    r"(?:né|née|nés|nées|naissance)\s*(?:le|:)?\s*"
    r"(\d{1,2}(?:er)?[\s/.-](?:\d{1,2}|janvier|février|fevrier|mars|avril|mai|juin|juillet|"
    r"ao[uû]t|septembre|octobre|novembre|décembre|decembre)[\s/.-]\d{2,4})",
    re.IGNORECASE,
)

#: A French postcode with the town after it: the pair locates a person far
#: more precisely than either half alone.
POSTCODE_TOWN = re.compile(r"\b(\d{5}[ \t]+[A-ZÀ-Ý][\wà-ÿ]+(?:[- \t][A-ZÀ-Ý]?[\wà-ÿ]+)*)")

#: A street line: number, street type, name.
STREET = re.compile(
    r"\b(\d{1,4}(?:\s?(?:bis|ter))?\s+(?:rue|avenue|av\.|boulevard|bd|impasse|allée|allee|"
    r"chemin|route|place|cours|quai|voie|résidence|residence)\s+[^,\n;]{2,40})",
    re.IGNORECASE,
)


def nir_is_valid(digits: str) -> bool:
    """13 digits then a 2-digit key equal to 97 minus the number mod 97."""
    normalised = re.sub(r"[\s.]", "", digits).upper()
    if len(normalised) != 15:
        return False
    body, key = normalised[:13], normalised[13:]
    # Corsica: the department is 2A or 2B, substituted before the arithmetic.
    body = body.replace("2A", "19").replace("2B", "18")
    if not body.isdigit() or not key.isdigit():
        return False
    return int(key) == 97 - (int(body) % 97)


def iban_is_valid(value: str) -> bool:
    """ISO 7064 mod 97: rotate the first four characters, letters to digits."""
    compact = value.replace(" ", "").upper()
    if len(compact) < 15 or not compact[:2].isalpha() or not compact[2:4].isdigit():
        return False
    rotated = compact[4:] + compact[:4]
    try:
        numeric = "".join(str(int(ch, 36)) for ch in rotated)
    except ValueError:
        return False
    return int(numeric) % 97 == 1


def luhn_is_valid(value: str) -> bool:
    digits = re.sub(r"[\s.]", "", value)
    if not digits.isdigit():
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


# La Poste is the documented exception to the Luhn check on SIREN.
LA_POSTE_SIREN = "356000000"


def siret_is_valid(value: str) -> bool:
    digits = re.sub(r"[\s.]", "", value)
    if len(digits) != 14:
        return False
    if digits.startswith(LA_POSTE_SIREN):
        return sum(int(d) for d in digits) % 5 == 0
    return luhn_is_valid(digits)


def siren_is_valid(value: str) -> bool:
    digits = re.sub(r"[\s.]", "", value)
    if len(digits) != 9:
        return False
    return digits == LA_POSTE_SIREN or luhn_is_valid(digits)


CHECKED = (
    ("nir", NIR, lambda m: nir_is_valid(m.group(0)), "numéro de sécurité sociale, clé modulo 97 vérifiée"),
    ("iban", IBAN, lambda m: iban_is_valid(m.group(0)), "IBAN, contrôle ISO 7064 vérifié"),
    ("siret", SIRET, lambda m: siret_is_valid(m.group(0)), "SIRET, clé de Luhn vérifiée"),
    ("siren", SIREN, lambda m: siren_is_valid(m.group(0)), "SIREN, clé de Luhn vérifiée"),
    ("email", EMAIL, lambda m: True, "adresse électronique"),
    ("phone", PHONE_FR, lambda m: True, "numéro de téléphone français"),
    ("plate", PLATE, lambda m: True, "immatriculation"),
    ("reference", REFERENCE, lambda m: True, "référence de dossier ou de matricule"),
)

#: Formats carrying a check digit, and the words to describe them when it
#: does not hold.
_KEYED = {
    "nir": "numéro de sécurité sociale",
    "iban": "IBAN",
    "siret": "SIRET",
    "siren": "SIREN",
}

#: Same certainty tier, but the value is a capture group rather than the
#: whole match: "né le 12 mars 1978" reports the date, not the verb.
#: The last field says whether the captured text needs its tail cleaned
#: up: a street line does, a postcode line must not, since its town is
#: half of what makes the pair worth masking.
CHECKED_GROUPS = (
    ("birth_date", BIRTH_DATE, "date de naissance, annoncée comme telle", False),
    ("address", STREET, "adresse postale", True),
    ("address", POSTCODE_TOWN, "code postal et commune", False),
)

#: A street line ends at its street name. The regex stops at a comma or a
#: line break, which leaves two kinds of debris: the full stop closing the
#: sentence, and the town announced by "à". Both were showing up inside
#: the value, so the grid offered "14 rue Edouard Delanglade." with its
#: period and "8 chemin de la Nerthe a Marseille" with the town swallowed,
#: and the town then had no row of its own.
_ADDRESS_PUNCTUATION = re.compile(r"[\s.,;:]+$")
_ADDRESS_TOWN = re.compile(r"\s+[aà]\s+[A-ZÀ-Ý][\wà-ÿ'’-]*$")


def _trim_address(value: str) -> str:
    return _ADDRESS_PUNCTUATION.sub("", _ADDRESS_TOWN.sub("", _ADDRESS_PUNCTUATION.sub("", value)))


# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------

CIVILITIES = (
    "M.", "Mme", "Mlle", "MM.", "Monsieur", "Madame", "Mademoiselle",
    "Maître", "Me", "Dr", "Docteur", "Pr", "Professeur",
)
COMPANY_FORMS = (
    "SAS", "SASU", "SARL", "EURL", "SA", "SCI", "SNC", "SCOP", "SCP", "SELARL",
    "GIE", "Association", "Société", "Ste", "Sté", "Entreprise", "Groupe",
)

CIVILITY_NAME = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in CIVILITIES) + r")\s+"
    r"([A-ZÀ-Ý][\w'’\-]+(?:\s+[A-ZÀ-Ý][\w'’\-]+)?)"
)
COMPANY_NAME = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in COMPANY_FORMS) + r")\s+"
    r"([A-ZÀ-Ý][\w'’\-]+(?:\s+[A-ZÀ-Ý&][\w'’\-]*){0,3})"
)
#: An elided article glued to a capitalised word: L'attestation, D'Artagnan.
#: The first form is not a name and the second is, so the apostrophe is cut
#: only when a single letter precedes it.
ELISION = re.compile(r"^[A-ZÀ-Ý]['’]")

#: Hyphenated names read as one token: Aix-en-Provence, Jean-Pierre,
#: Sainte-Marie. Splitting them produced half-names in the grid.
WORD = r"[A-ZÀ-Ý][\wà-ÿ]*(?:[-'’][\w\wà-ÿ][\wà-ÿ]*)*"
#: Runs of capitalised words read as one token. Acts write party names in
#: capitals, often two or three words long: taking "MECANIQUE PROVENCALE"
#: as two findings produced half-names in the grid and a table entry for
#: "MECANIQUE" that never matched anything on its own.
#: A run never crosses a line break. With ``\s+`` between words, a
#: signature block read as one name: "Barreau de Marseille\nCabinet
#: Moreau" came out as the single value "Marseille Cabinet Moreau".
_GAP = r"[ \t]+"
ALL_CAPS = re.compile(
    rf"\b[A-ZÀ-Ý][A-ZÀ-Ý]{{1,}}(?:[-'’][A-ZÀ-Ý]+)*(?:{_GAP}[A-ZÀ-Ý][A-ZÀ-Ý'’\-]+)*\b"
)
#: Runs of title-case words read as one token too, for the same reason as
#: ALL_CAPS: "Mecanique Provencale" appearing without its company form in
#: a header produced three separate rows and three unrelated pseudonyms.
_TITLE_WORD = r"[A-ZÀ-Ý][a-zà-ÿ]+(?:[-'’](?:[A-ZÀ-Ý]|[a-zà-ÿ])[a-zà-ÿ]*)*"
CAPITALISED = re.compile(rf"\b{_TITLE_WORD}(?:{_GAP}{_TITLE_WORD})*\b")

#: Closed vocabulary of the field. A capitalised word in here is not a name.
LEGAL_LEXICON = frozenset(
    w.upper() for w in """
    Cour Cassation Appel Tribunal Conseil Chambre Section Juge Président
    Prud Prudhommes Prud'hommes Instance Grande Judiciaire Administratif
    Etat État Ministre Ministère République Française France Journal Officiel
    Code Travail Civil Pénal Commerce Procédure Sécurité Sociale Article
    Articles Livre Titre Alinéa Décret Loi Arrêté Ordonnance Circulaire
    Convention Collective Accord National Interprofessionnel Avenant Annexe
    Contrat Durée Indéterminée Déterminée Lettre Licenciement Faute Grave
    Lourde Cause Réelle Sérieuse Préavis Indemnité Rupture Conventionnelle
    Démission Mise Pied Avertissement Entretien Préalable Comité Economique
    Économique Social Délégué Syndical Personnel Inspection Médecine
    Employeur Salarié Salariée Demandeur Demanderesse Défendeur Défenderesse
    Requérant Partie Parties Conseil Avocat Barreau Greffe Audience Jugement
    Arrêt Ordonnance Décision Attestation Pièce Pièces Bordereau Conclusions
    Bulletin Bulletins Recueil Revue Chronique Note Observations Commentaire
    Monsieur Madame Mademoiselle Maître Docteur Professeur
    Janvier Février Mars Avril Mai Juin Juillet Août Septembre Octobre
    Novembre Décembre Lundi Mardi Mercredi Jeudi Vendredi Samedi Dimanche
    Objet Date Fait Vu Attendu Considérant Motifs Plaise
    Euros Euro TTC HT TVA SMIC URSSAF CPAM CSE CHSCT DRH RH PDG DG
    Il Elle Ils Elles Nous Vous Je Tu On Le La Les Un Une Des Du De Et Ou
    Ce Cette Ces Cet Celui Celle Ceux Celles Son Sa Ses Leur Leurs
    Notre Nos Votre Vos Mon Ma Mes Ton Ta Tes
    Si Mais Donc Or Ni Car Que Qui Quoi Dont Où Quand Comme Ainsi Enfin
    Cependant Toutefois Néanmoins Ensuite Puis Alors Après Avant Depuis
    Aux Au Sur Sous Dans Par Pour Avec Sans Entre Chez Vers Selon Entre
    En Y Lors Lorsque Dès Jusqu Pendant Durant Malgré Outre Hormis Sauf
    Aucun Aucune Chaque Tout Toute Tous Toutes Plusieurs Certains Certaines
    Même Mêmes Autre Autres Tel Telle Tels Telles Quelque Quelques
    Premièrement Deuxièmement Troisièmement Également Notamment Surtout
    Effectivement Evidemment Évidemment Partant Dès Ayant Etant Étant
    Compte Tenu Suite Concernant Relatif Relative Conformément
    Afin Puisque Bien Alors Pourtant Ainsi Aussi Encore Déjà Jamais
    Plus Moins Très Trop Peu Beaucoup Assez Bientôt Toujours Souvent
    Est Sont Était Étaient Sera Seront Fut Furent Soit Soient
    Avoir Être Faire Dire Voir Savoir Pouvoir Devoir Vouloir Falloir
    Cela Ceci Celà Ici Là Voici Voilà Non Oui Sans Avec
    Madame Monsieur Messieurs Mesdames
    """.split()
)

#: Structural words a pleading is built from. Added after measuring a real
#: two-page set of conclusions: each of these came up as a candidate and
#: cost a row for nothing.
DOCUMENT_FURNITURE = frozenset(
    w.upper() for w in """
    CONCLUSIONS RECAPITULATIVES RÉCAPITULATIVES RAPPEL FAITS DISCUSSION
    CONTRE POUR OBJET SOMMAIRE PLAN INTRODUCTION CONCLUSION ANNEXES
    PIECES PIÈCES BORDEREAU PRODUCTION DEBATS DÉBATS DEMANDES PRETENTIONS
    PRÉTENTIONS MOYENS EXPOSE EXPOSÉ PROCEDURE PROCÉDURE HISTORIQUE
    RCS SIRET SIREN IBAN BIC TVA URSSAF SMIC
    Confidentiel Confidentielle Copie Original Brouillon Version Final Finale
    Projet Note Memo Mémo Fiche Synthese Synthèse Rapport Compte Rendu
    Document Documents Lettre Courriel Annexe Annexes Extrait Extraits
    Cabinet Etude Étude Selarl Scp Barreau Ordre Batonnier Bâtonnier
    Telephone Téléphone Portable Fax Courriel Mail Adresse Email
    Reference Référence Dossier Affaire Numero Numéro
    Ancien Ancienne Nouveau Nouvelle Present Présent Presente Présente
    Premier Première Second Seconde Troisieme Troisième
    Brut Net Mensuel Annuel Horaire Total Montant Somme Solde
    Contact Contacts Verifier Vérifier Voir Noter Confirmer Relire Rappel
    Cass Civ Soc Crim Com Bull Dalloz JCP AJDA RJS Gaz Pal CJUE CEDH
    TGI RG CA CE TJ Pourvoi Arret Arrêt Attendu Juris Jurisprudence
    SAS SASU SARL EURL SA SCI SNC SCOP SCP SELARL GIE Societe Société Ste Sté
    """.split()
)

#: The furniture of a letter. A mail is mostly greeting, thanks and
#: sign-off, and every one of those words is capitalised: without this
#: list a thousand-word exchange spent eight of its rows on "Merci",
#: "Chère Consoeur" and the "RE" of its own subject line.
CORRESPONDENCE = frozenset(
    w.upper() for w in """
    Cher Chère Chers Chères Bonjour Bonsoir Madame Monsieur Messieurs
    Confrère Consoeur Consœur Confrères Consoeurs Consœurs Maitre Maître
    Merci Remerciements Cordialement Confraternellement Sincèrement
    Salutations Respectueusement Amicalement Bien Veuillez Agréer
    Croire Expression Sentiments Considération Distinguée Distinguées
    Dévoué Dévouée Sentiments Meilleures Excellente Réception Accusé
    Dites Dites-moi Dis Dis-moi Rappelle Rappelle-moi Tiens Tiens-moi
    Merci-beaucoup Pardon Désolé Desole Navré Navre
    RE TR FW FWD REF Objet Sujet Copie Transfert Transféré Transfere
    Pièce Pieces Jointe Jointes Attaché Attachee Ci-joint Ci-dessous
    Un Deux Trois Quatre Cinq Six Sept Huit Neuf Dix Onze Douze
    Premier Premièrement Deuxièmement Troisièmement Quatrièmement
    Situation Question Questions Réponse Reponse Point Points Sujet
    Associés Associes Partenaires Collaborateurs Confraternelle
    Entretien Échange Echange Appel Téléphonique Telephonique Courrier
    """.split()
)

#: Abbreviated civilities. The long forms were already here, the short
#: ones were not, so "Mme Lenoir" read as a first name and a surname and
#: the masked text said "Romain Mercier" where it should have said "Mme
#: Mercier". ``Me`` is the abbreviation of ``Maître``; as a capitalised
#: standalone word it is never anything else.
CIVILITY_WORDS = frozenset(
    w.upper() for w in "Mme Mmes Mlle Mlles MM Me Mes Dr Drs Pr Prs Mgr".split()
)

#: Job titles and the ordinary nouns of an employment file. Measured on a
#: set of conclusions and a mail thread: every one of these took a row,
#: and a row the reader has to think about costs more than it saves.
#: "Chef" and "Fondement" were table headings; "Dommages-intérêts" is one
#: hyphenated token, so it has to be listed as one.
OCCUPATIONS = frozenset(
    w.upper() for w in """
    Chef Cheffe Assistant Assistante Secretaire Secrétaire Juriste Stagiaire
    Collaborateur Collaboratrice Clerc Huissier Commissaire Expert Experte
    Greffier Greffiere Greffière Notaire Mediateur Médiateur Conciliateur
    Directeur Directrice Responsable Gerant Gérant Gerante Gérante
    Technicien Technicienne Ouvrier Ouvriere Ouvrière Employe Employé
    Employee Employée Cadre Agent Charge Chargé Chargee Chargée Avocate
    Mandataire Liquidateur Administrateur Comptable Ingenieur Ingénieur
    Fondement Montant Decompte Décompte Rendement Insuffisance
    Professionnel Professionnelle Reserve Reserves Réserves Aptitude
    Alerte Signalement Signalements Convocation Production Releve Relevé
    Releves Relevés Moyenne Perte Pertes Revenu Revenus Virement Matricule
    Portabilite Portabilité Mutuelle Caisse Atelier Ateliers Equipe Équipe
    Poste Postes Direction Siege Siège Succursale Agence Etablissement
    Établissement Industrie Industries Industriel Industrielle
    Dommages-interets Dommages-intérêts Interets Intérêts Dommages
    Pole Pôle CPC CPH Climat Cadence Cadences Preuve Preuves Charge
    Ressources Humaines Humaine Service Services Personnel
    """.split()
)

#: Question openers of a letter, which are capitalised and hyphenated and
#: therefore read as one capitalised token: "Pouvez-vous" was offered as a
#: name and masked into "Sabine", so the sentence came back as "Sabine
#: verifier auprès de...".
QUESTION_OPENERS = frozenset(
    w.upper() for w in """
    Pouvez-vous Pourriez-vous Auriez-vous Avez-vous Seriez-vous Serait-il
    Est-il Est-ce Faut-il Peut-on Pensez-vous Savez-vous Voulez-vous
    Confirmez-vous Merci-de Peux-tu Peut-elle Peut-il
    """.split()
)

#: Roman numerals number the sections of a pleading: I, II, III, IV.
ROMAN = re.compile(r"^[IVXLCDM]{1,7}$")

#: Words that commonly open a sentence and are therefore capitalised without
#: being names. Separate from the legal lexicon so each list stays readable.
SENTENCE_OPENERS = frozenset(
    w.upper() for w in """
    Le La Les Un Une Des Du De Au Aux Ce Cet Cette Ces Son Sa Ses Leur Leurs
    Il Elle Ils Elles On Nous Vous Je Tu Cela Ceci Celui Celle Ceux Celles
    Par Pour Dans Sur Sous Avec Sans Entre Chez Vers Selon En Y Lors Dès
    Si Mais Donc Or Ni Car Que Qui Quoi Dont Où Quand Comme Ainsi Aussi
    Cependant Toutefois Néanmoins Ensuite Puis Alors Après Avant Depuis
    Enfin Pourtant Partant Puisque Lorsque Bien Afin Compte Suite
    Attendu Considérant Vu Fait Plaise Objet Date Première Deuxième Second
    Aucun Aucune Chaque Tout Toute Tous Toutes Plusieurs Certains Certaines
    Même Autre Autres Tel Telle Quelque Quelques Notamment Également
    """.split()
)

#: Markers that a citation, and therefore a public party name, is at hand.
#:
#: Deliberately only unambiguous ones. Short forms such as ``D.``, ``CE``,
#: ``TJ`` or a bare ``Soc.`` occur constantly in ordinary prose; including
#: them painted citation zones across whole documents, and the client's own
#: name ended up marked "keep", which is the one mistake that must not
#: happen. ``Cass.`` already covers ``Cass. soc.`` and ``Cass. civ.``.
CASE_LAW_MARKERS = (
    r"Cass\.", r"Cassation", r"C\.\s?cass",
    r"CA\s+[A-ZÀ-Ý]", r"C\.A\.\s+[A-ZÀ-Ý]",
    r"Conseil d['’]É?Etat", r"Conseil d['’]État",
    r"CJUE", r"CEDH", r"TGI\s+[A-ZÀ-Ý]",
    r"pourvoi", r"req\.\s?n", r"RG\s?n", r"n°\s?RG",
    r"Bull\.", r"Dalloz", r"JCP", r"AJDA", r"RJS", r"Gaz\.\s?Pal",
)

#: A citation zone ends where its sentence does, rather than after a fixed
#: number of characters: a count either cuts a long citation in half or
#: spills onto the paragraph after it.
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý])|\n")
CASE_LAW_MAX = 200


def case_law_zones(text: str) -> list[tuple[int, int]]:
    """Character ranges around a citation marker, where names must be kept."""
    zones: list[tuple[int, int]] = []
    for marker in CASE_LAW_MARKERS:
        for match in re.finditer(marker, text):
            zones.append((_start_of_citation(text, match.start()),
                          _end_of_citation(text, match.end())))
    return _merge(zones)


#: A citation opened by a parenthesis names its party just before it:
#: "dans l'affaire Societe Bergerat Monnoyeur (Cass. soc., 25 septembre
#: 2019)". The marker is inside the brackets and the name is outside, so a
#: zone starting at the marker left that name unprotected while the same
#: name written "(Cass. soc. ..., Societe Novandie)" was kept. One of the
#: two was masked and the other not, in the same paragraph.
_OPENS_A_CITATION = re.compile(r"\(\s*$")


def _start_of_citation(text: str, start: int) -> int:
    """Where the sentence holding a bracketed citation begins.

    Widening backwards is safe because of the rule in :func:`group`: a row
    counts as case law only when *every* one of its occurrences sits in a
    zone. A client mentioned in the same sentence as a citation is still
    masked, because the client is named elsewhere too.
    """
    if not _OPENS_A_CITATION.search(text[:start]):
        return start
    floor = max(0, start - CASE_LAW_MAX)
    breaks = list(SENTENCE_BREAK.finditer(text, floor, start))
    return breaks[-1].end() if breaks else floor


def _end_of_citation(text: str, start: int) -> int:
    ceiling = min(len(text), start + CASE_LAW_MAX)
    # A citation is full of abbreviating full stops ("Cass. soc. 25 sept."),
    # so the break has to be a full stop followed by a new sentence, and the
    # search skips the abbreviations immediately after the marker.
    found = SENTENCE_BREAK.search(text, start, ceiling)
    return found.start() if found else ceiling


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _in_zone(start: int, end: int, zones: list[tuple[int, int]]) -> bool:
    return any(z_start <= start and end <= z_end for z_start, z_end in zones)


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


_EXCLUDED = frozenset(
    _fold(w).upper()
    for w in (LEGAL_LEXICON | SENTENCE_OPENERS | DOCUMENT_FURNITURE | CORRESPONDENCE
              | CIVILITY_WORDS | OCCUPATIONS | QUESTION_OPENERS)
)


def _is_excluded(word: str) -> bool:
    """Position is deliberately not a filter.

    Discarding capitalised words that open a sentence would silence
    ``Dupont conteste cette analyse.``, which is exactly how conclusions
    are written. Only the closed lists exclude, so what is excluded can be
    read, argued with and extended.
    """
    return bool(ROMAN.match(word)) or _fold(word).upper() in _EXCLUDED


def _trim_excluded(word: str, start: int) -> tuple[str, int]:
    """Drop excluded words from the edges of a multi-word capitalised run.

    ``PLAISE AU CONSEIL DE PRUD'HOMMES DE MARSEILLE`` is one run of
    capitals, but only the last word is a name. Trimming from both ends
    keeps the useful middle without splitting genuine two-word names.
    """
    words = word.split()
    if len(words) < 2:
        return word, start

    leading = 0
    while leading < len(words) and _is_excluded(words[leading]):
        leading += 1
    trailing = len(words)
    while trailing > leading and _is_excluded(words[trailing - 1]):
        trailing -= 1

    if leading >= trailing:
        return "", start
    offset = len(" ".join(words[:leading])) + (1 if leading else 0)
    return " ".join(words[leading:trailing]), start + offset


def find(text: str, known: list[str] | None = None) -> list[Finding]:
    """Everything worth showing the user, in document order, de-overlapped."""
    zones = case_law_zones(text)
    findings: list[Finding] = []

    for kind, pattern, check, why in CHECKED:
        for match in pattern.finditer(text):
            if check(match):
                findings.append(Finding(match.group(0), match.start(), match.end(),
                                        kind, Certainty.CERTAIN, why))
            elif kind in _KEYED:
                # Right shape, wrong check digit. Almost always a typo in
                # the document, and the number identifies its holder just
                # as well as a correct one would. Dropping it silently
                # would leave a social security number in plain sight, so
                # it is offered rather than discarded.
                findings.append(Finding(
                    match.group(0), match.start(), match.end(), kind, Certainty.CONFIRM,
                    f"format d'un {_KEYED[kind]}, mais la clé de contrôle ne tombe pas juste",
                ))

    for kind, pattern, why, trim in CHECKED_GROUPS:
        for match in pattern.finditer(text):
            start, end = match.span(1)
            value = match.group(1).strip()
            if trim:
                value = _trim_address(value)
                if not value:
                    continue
                end = start + len(value)
            findings.append(Finding(value, start, end, kind, Certainty.CERTAIN, why))

    for value in known or []:
        for match in re.finditer(re.escape(value), text):
            findings.append(Finding(match.group(0), match.start(), match.end(), "declared",
                                    Certainty.CERTAIN, "déclaré au dossier"))

    for pattern, kind, why in (
        (CIVILITY_NAME, "name", "précédé d'une civilité"),
        (COMPANY_NAME, "org", "précédé d'une forme sociale"),
    ):
        for match in pattern.finditer(text):
            start, end = match.span(2)
            certainty = Certainty.CASE_LAW if _in_zone(start, end, zones) else Certainty.CONFIRM
            findings.append(Finding(match.group(2), start, end, kind, certainty,
                                    why if certainty is Certainty.CONFIRM else "partie à une décision citée"))

    for pattern in (ALL_CAPS, CAPITALISED):
        for match in pattern.finditer(text):
            word, start = match.group(0), match.start()
            if ELISION.match(word):
                start += 2
                word = word[2:]
                if not word or not word[0].isupper():
                    continue
            word, start = _trim_excluded(word, start)
            if not word or _is_excluded(word):
                continue
            certainty = Certainty.CASE_LAW if _in_zone(start, match.end(), zones) else Certainty.CONFIRM
            why = ("partie à une décision citée" if certainty is Certainty.CASE_LAW
                   else "mot capitalisé hors vocabulaire juridique")
            findings.append(Finding(word, start, match.end(), "candidate", certainty, why))

    findings.extend(_other_spellings(text, findings))
    return _deduplicate(findings)


#: Shorter than this, a lower-case match is far more likely to be an
#: ordinary word than the same name written carelessly.
_MIN_VARIANT = 4


def _other_spellings(text: str, findings: list[Finding]) -> list[Finding]:
    """The same name written in a case nobody looked for.

    Every rule above starts from a capital letter, so a surname typed in
    lower case mid-sentence is invisible to all of them. In the mail
    fixture, "priver benzaoui des trajets" went out in the masked copy
    with the client's real name in it, and nothing anywhere lit up.

    Once a name has been found in any spelling, its other spellings are
    searchable: this looks for them case-insensitively and offers what it
    finds. It offers rather than decides, because a surname can also be
    an ordinary word, and masking every "roux" in a file that mentions a
    Madame ROUX would wreck the text. The row says where it comes from so
    the choice is informed.
    """
    # Only names something in the sentence vouched for: a civility, a
    # company form, or the user's own declaration. Searching every
    # capitalised candidate instead turned "Bulletin", kept as a case-law
    # marker, into a reason to mask "bulletins de paie".
    #
    # A capitalised run of two words or more vouches for itself. "par
    # Karim Benhaddou" carries no civility and no company form, so the
    # row came out a bare candidate, nothing searched for its other
    # spellings, and "Ensuite, benhaddou a envoyé" went out in clear in
    # the masked copy. Two words is the whole of the rule: a single
    # capitalised word is as likely to be "Bulletin", and vouching for
    # that one turned "bulletins de paie" into a name.
    vouched = {f.value for f in findings if f.kind in ("name", "org", "declared")}
    vouched |= {f.value for f in findings
                if f.kind == "candidate" and len(f.value.split()) > 1}
    known = {
        word
        for value in vouched
        for word in value.replace("'", " ").replace("’", " ").split()
        if len(word) >= _MIN_VARIANT and not _is_excluded(word)
    }
    taken = [(f.start, f.end) for f in findings]
    extra: list[Finding] = []

    for value in sorted(known):
        for match in re.finditer(rf"\b{re.escape(value)}\b", text, re.IGNORECASE):
            if match.group(0) == value:
                continue
            start, end = match.span()
            if any(start < t_end and end > t_start for t_start, t_end in taken):
                continue
            taken.append((start, end))
            extra.append(Finding(
                match.group(0), start, end, "candidate", Certainty.CONFIRM,
                f"même nom que « {value} », écrit ici sans majuscule",
            ))
    return extra


_RANK = {Certainty.CERTAIN: 0, Certainty.CASE_LAW: 1, Certainty.CONFIRM: 2}


def _deduplicate(findings: list[Finding]) -> list[Finding]:
    """Keep the longest, most certain finding over any overlapping span."""
    ordered = sorted(findings, key=lambda f: (f.start, -(f.end - f.start), _RANK[f.certainty]))
    kept: list[Finding] = []
    for finding in ordered:
        if any(finding.start < k.end and finding.end > k.start for k in kept):
            continue
        kept.append(finding)
    return kept


def group(findings: list[Finding]) -> list[tuple[str, Certainty, str, int, str]]:
    """One row per distinct value: a name seen 200 times is one decision.

    Returned as (value, certainty, why, occurrences, kind), most certain
    first. The kind travels with the row because certainty alone cannot
    say what a value *is*: a social security number whose check digit
    fails drops to "confirm", and a row that only knows its certainty
    would hand it a person's name instead of a placeholder.

    A row is marked "keep as case law" only when *every* occurrence of the
    value sits inside a citation. One appearance in ordinary text and the
    row goes back to being a candidate for replacement: a client who
    happens to share a surname with a cited party must not be shielded by
    the citation. The asymmetry is deliberate, and it errs towards masking.
    """
    rows: dict[str, list[Finding]] = {}
    for finding in findings:
        rows.setdefault(finding.value, []).append(finding)

    summary = []
    for value, items in rows.items():
        certainty = _row_certainty(items)
        why = next((f.why for f in items if f.certainty is certainty), items[0].why)
        summary.append((value, certainty, why, len(items), _row_kind(items)))
    return sorted(summary, key=lambda row: (_RANK[row[1]], -row[3], row[0]))


#: Kinds that name a datum rather than a person or an organisation.
IDENTIFIER_KINDS = frozenset(
    {"nir", "iban", "siret", "siren", "email", "phone", "plate", "birth_date",
     "address", "reference"}
)


def _row_kind(items: list[Finding]) -> str:
    """An identifier anywhere in the row makes the whole row an identifier."""
    for finding in items:
        if finding.kind in IDENTIFIER_KINDS:
            return finding.kind
    return items[0].kind


def _row_certainty(items: list[Finding]) -> Certainty:
    if any(f.certainty is Certainty.CERTAIN for f in items):
        return Certainty.CERTAIN
    if all(f.certainty is Certainty.CASE_LAW for f in items):
        return Certainty.CASE_LAW
    return Certainty.CONFIRM
