# docx-anonymizer

A local, offline tool that lets a lawyer submit working documents to an
AI without any identifying data leaving the office.

Two ways in: paste some text, or open a Word file. Same table, same
checks, same way back.

## Why this is not a find-and-replace

Word splits a visible word across several runs for reasons that have
nothing to do with meaning. `DUPONT` is commonly stored as `DUP` + `ONT`
because of a spell-check boundary or a formatting toggle. Searching the
markup for `DUPONT` finds nothing, and the document looks clean while the
name is plainly readable on screen.

The engine concatenates a paragraph's `<w:t>` nodes, works on the
resulting string, and writes back node by node. Nothing but the text of
those nodes is touched.

## Where identity hides in a .docx

| Location | What it holds |
| --- | --- |
| `word/document.xml` | The visible text, including text boxes |
| `word/header*.xml`, `footer*.xml` | Firm name, case reference, client name |
| `word/footnotes.xml`, `endnotes.xml` | Named references |
| `word/comments.xml` | Comment text, plus each comment's author and initials |
| `w:ins`, `w:del` attributes | The author stamped on every tracked change |
| `<w:instrText>` | Field codes: MERGEFIELD, HYPERLINK, AUTHOR |
| `*.rels` targets | `mailto:` links carrying a full address |
| `docProps/core.xml`, `app.xml` | Author, last modified by, company, title |
| Entry names | Often the most talkative part of a document |

## How names are found, without a model

Three tiers, all local, nothing sent anywhere.

**Check-digit formats.** A social security number (modulo 97), an IBAN
(ISO 7064), a SIRET or SIREN (Luhn, with La Poste as the documented
exception). Either the arithmetic holds or the string is not one. A
number whose key *fails* is still offered rather than discarded: almost
always a typo, and it identifies its holder just as well.

**Declared names and their spellings**, generated from what the user
typed, never guessed from the document.

**Over-detection.** Rather than recognising names, eliminate what cannot
be one — known legal vocabulary, sentence openers, the structural words a
pleading is built from — and offer the rest. Exhaustive by construction
for capitalised names. The cost is rows to arbitrate, not missed names.

Position is deliberately not a filter: discarding capitalised words that
open a sentence would silence `Dupont conteste cette analyse.`, which is
exactly how pleadings are written.

**Case-law parties are kept, not masked.** Masking the name in
`Cass. soc. 25 septembre 2013, Sté Delattre` destroys the citation and
the reasoning that rests on it. A row is marked "keep" only when *every*
occurrence sits inside a citation: a client who happens to share a
surname with a cited party must not be shielded by it.

### What that costs in practice

Measured on a realistic two-page pleading (`tests/sample_conclusions.txt`)
and pinned as a budget test:

| | |
| --- | --- |
| Rows to arbitrate | 35 |
| Identifiers found with certainty | 12 |
| Cited parties correctly kept | 3 |
| People or companies in the file that were missed | 0 |

## What the masked text reads like

Spellings of one person get one pseudonym, shaped to match each
spelling: `Jean DUPONT`, `DUPONT` and `Dupont` become `Damien VANEL`,
`VANEL` and `Vanel`. Three unrelated pseudonyms would turn one man into
three people, which is worse than useless to an AI asked to follow an
argument.

The surrounding words decide what kind of name to use: a civility picks
the gender, a postcode or `Barreau de` picks a town, a company form picks
a company. Identifiers get a numbered placeholder — `[adresse 2]`,
`[date de naissance 1]` — rather than a plausible fake, which would
invite someone downstream to treat it as real.

Known cosmetic defect: elision is not adjusted, so `d'Aix-en-Provence`
masks to `d'Beauvoir`.

## The refusal check, and what it does not do

Before writing anything, the engine reads back what it produced and looks
for every value in the table. One hit and it writes nothing.

The check scans *reconstructed paragraph text* for story parts, not raw
XML, precisely because of the split-run problem above.

The limit, pinned by a test so it cannot quietly disappear: the check
only looks for values that are **in the table**. A name nobody declared
is not searched for and will go out. Detection and the refusal check are
two separate lines of defence; neither replaces the other.

## The return trip fails differently

Looking for leftover pseudonyms after restoring proves nothing: the
substitution just removed every one it could see, so the search is always
empty.

The failure that matters is a pseudonym the model or the user *reworded*.
`Marc Lemoine` coming back as `Marc Lemoyne` matches nothing, is never
restored, and the document would go out half real and half invented. The
only way to see it is from the other end: a table entry that fired on the
way out and is nowhere in the returned document. That is what is checked,
before substituting.

## What a round trip preserves, exactly

"Byte-for-byte identical after a round trip" would be false, and a test
asserting it would be a test written to pass. Once `DUP` + `ONT` becomes
`MARTIN` + `""`, putting `DUPONT` back produces one run, not two.

What is asserted, and verified in `tests/test_roundtrip.py`:

- a document with nothing to replace comes out **byte for byte identical**;
- the full text after a round trip equals the original text;
- every node that is not a `<w:t>` survives unchanged, which is what
  carries the layout: styles, justification, tracked changes, section
  properties, text boxes;
- parts with no match are never rewritten at all;
- images are never altered.

## Offline, and checkable

The program blocks its own outbound connections and shows, in the window,
whether any were attempted. Green means nothing tried to leave.

This is a safety net over an honest program, not a sandbox: it runs
inside the process, so it constrains mistakes and dependencies rather
than a determined attacker. The real guarantee is that the source is
public and has no network code in it. The guard makes that absence
visible to someone who cannot read the source. Loopback is allowed and
counted separately, since it never leaves the machine.

## Not covered, by design

- **Text inside images.** A scanned signature, a stamp, a screenshot of a
  mail client. They are counted and reported, never silently passed over.
- **PDF and scanned documents.** Word files only.
- **Names nobody declared and that detection missed.** See the limit above.
- **Judgement about what is sensitive.** The tool applies what it is told.
- **Re-identification from context.** A twelve-person company in a named
  town stays recognisable with every name removed.

## Running it

```
pip install -e .
PYTHONPATH=src:tests python -m unittest discover -s tests -v

dxanon scan conclusions.docx --mapping case.json
dxanon anonymize conclusions.docx conclusions_ANON.docx --mapping case.json
dxanon restore conclusions_ANON_corrige.docx conclusions_final.docx --mapping case.json
```

`scan` decides nothing: it prints what would be masked and writes a
proposed table for review.

The window is `python -m dxanon` (needs PySide6). `python -m dxanon
--self-check` exercises every layer and exits, which is how the Windows
build proves the bundle is complete.

The mapping file holds exactly what the exercise is meant to protect. It
never travels inside an exported document, and it is treated like the
rest of the case file.

## What is not verified

**The window.** The test suite runs headless, so `gui.py` is parsed,
checked for dead imports and for calls into functions that still exist,
and imported against a real PySide6 in CI. None of that is the same as
opening it. Until someone uses it on Windows, its behaviour is unverified.

**Word itself.** The tests assert the XML and the text. Whether Word
renders a produced file exactly as before has to be checked by opening
one.

**The signed build.** The executable is unsigned, so Windows will warn on
first launch. That needs a code-signing certificate, not a code change.
