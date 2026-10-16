# docx-anonymizer

A local, offline tool that lets a lawyer submit working documents to an AI
without any identifying data leaving the office.

Status: **engine only**. No interface yet. The part that has to be right
is the substitution core, and it is testable without a window.

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

Covered by the engine:

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

Not covered, by design and stated rather than hidden:

- **Text inside images.** A scanned signature, a stamp, a screenshot of a
  mail client. They are counted and reported, never silently passed over.
- **PDF and scanned documents.** Word files only.
- **Names nobody declared.** See the limit below.

## The refusal check, and what it does not do

Before writing anything, the engine reads back what it produced and looks
for every value in the table. One hit and it writes nothing.

The check scans *reconstructed paragraph text* for story parts, not raw
XML, precisely because of the split-run problem above. Everything else is
scanned raw.

The limit, pinned by a test so it cannot quietly disappear: the check only
looks for values that are **in the table**. A name nobody declared is not
searched for and will go out. Detection and the refusal check are two
separate lines of defence; neither replaces the other.

## The return trip fails differently

Looking for leftover pseudonyms after restoring proves nothing: the
substitution just removed every one it could see, so the search is always
empty.

The failure that matters is a pseudonym the model or the user *reworded*.
`Marc Lemoine` coming back as `Marc Lemoyne` matches nothing, is never
restored, and the document would go out half real and half invented. The
only way to see it is from the other end: a pseudonym that is in the table
and nowhere in the returned document. That is what is checked, before
substituting.

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

## Running it

```
pip install -e .
PYTHONPATH=src:tests python -m unittest discover -s tests -v

dxanon add --mapping case.json --with-variants "Jean Dupont" "Marc Lemoine"
dxanon anonymize conclusions.docx conclusions_ANON.docx --mapping case.json
dxanon restore conclusions_ANON_corrige.docx conclusions_final.docx --mapping case.json
```

The mapping file holds exactly what the exercise is meant to protect. It
never travels inside an exported document, and it is treated like the rest
of the case file.

## Next

- Detection: check-digit formats (NIR, IBAN, SIRET), INSEE name lists,
  over-detection of capitalised words with a closed legal lexicon.
- Case-law names must be **kept**, not replaced: a citation whose party
  name is masked loses its meaning.
- A pasted-text mode alongside the file mode.
- The Windows interface, and a signed build.
