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

**Other spellings of a name already found.** Every rule above starts
from a capital letter, so a surname typed in lower case mid-sentence is
invisible to all of them: in the mail fixture, "priver benzaoui des
trajets" went out in the masked copy with the client's real name in it.
Once a name has been found in any spelling, its other spellings are
searchable. This runs only on names something in the sentence vouched
for, a civility, a company form or the user's own declaration, because a
surname can also be a common noun and masking every "bulletin" in a file
that cites the Bulletin would wreck the text.

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

| | Conclusions, 2 pages | Mail thread, 1055 words | Mail thread, 436 words |
| --- | --- | --- | --- |
| Rows to arbitrate | 35 | 48 | 32 |
| Identifiers found with certainty | 12 | 14 | 15 |
| Cited parties correctly kept | 3 | 3 | 2 |
| People or companies missed | 0 | 0 | 0 |

All three figures are pinned as budget tests, so a change to the lexicon
or the patterns cannot quietly make the grid unusable in either
direction.

### The rows that were not worth arbitrating

The counts above are what is left after a pass spent entirely on what the
grid was asking for nothing. Measured on a fresh pleading and a fresh
mail thread, it took 41 rows down to 35 and 35 down to 32, and the rows
it removed were `Chef`, `Fondement` and `Montant` (table headings),
`Dommages-intérêts` and `CPC`, `Assistante` and `Avocate`,
`Pouvez-vous`, `Mme` read as a first name, and `AL` taken from the file
reference `AL-2025-77412`, which is now detected as the reference it is.

Three of those rows were worse than noise. `Mme Lenoir` was masked as
`Romain Mercier` rather than `Mme Mercier`; the file reference lost its
digits and kept its two letters as a name; and the invented company
`Orion Industries` held the word `Industrie`, which the document used for
the court's section, so the coherence check warned and the export refused
on a conflict the program had created itself. The same pass closed one
leak: a surname typed in lower case mid-sentence was only searched for
when a civility or a company form vouched for the name, which a mail
rarely provides, so `Ensuite, benhaddou a envoyé` went out in clear.

The mail thread was the harder document, and it is the one that found the
real defects: a letter is mostly greeting and sign-off, a company is
named in full once and in shorthand afterwards, and a signature block
puts a town and a firm on consecutive lines.

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

## One shot, and nothing on disk

The correspondence table maps every pseudonym back to the client. Written
to disk it becomes the most dangerous file in the case folder, outliving
the work that needed it, and then the tool needs a delete button to remove
what it should never have written.

So it is not written. The table exists in memory for the length of one
round trip: mask, work with the AI, restore, done. There is deliberately
no `save` on `Mapping`, because a save method is an invitation to call it.

**The cost, stated rather than discovered.** Close the window mid-cycle
and the real names are gone, and any document already masked can never be
turned back. The window says so in three places: a standing line on the
home screen while a cycle is live, a confirmation on "Effacer le cycle",
and a confirmation on closing the window itself.

**Erasing a cycle** is therefore just forgetting the table. There are no
files to hunt down, no leftovers in a hidden application folder, and
nothing a later audit of the firm's disk can turn up.

`tests/test_no_persistence.py` enforces this by watching the filesystem
rather than by reading the code: a full text cycle and a full file cycle
must leave behind exactly the files that were asked for and nothing else.

## Not covered, by design

- **Text inside images.** A scanned signature, a stamp, a screenshot of a
  mail client. They are counted and reported, never silently passed over.
- **PDF and scanned documents.** Word files only.
- **A name nobody declared, never capitalised anywhere in the document.**
  Lower-case spellings are now found, but only of names already seen with
  a capital somewhere.
- **Judgement about what is sensitive.** The tool applies what it is told.
- **Re-identification from context.** A twelve-person company in a named
  town stays recognisable with every name removed.

## Running it

```
pip install -e .
PYTHONPATH=src:tests python -m unittest discover -s tests -v

dxanon scan conclusions.docx
dxanon mask conclusions.docx conclusions_ANON.docx
dxanon roundtrip conclusions.docx
```

`scan` decides nothing: it prints what would be masked and stops.

`mask` writes the masked copy and prints the table to standard output,
never to a file: whoever runs it decides where it goes, and a closed
terminal takes it with it.

`roundtrip` masks and restores in one invocation and reports whether the
document came back unchanged. There is no separate `restore` command,
which is the honest consequence of storing nothing: there is nothing to
carry between two runs of a program that keeps no state.

The window is `python -m dxanon` (needs PySide6). `python -m dxanon
--self-check` exercises every layer and exits, which is how the Windows
build proves the bundle is complete.

The mapping file holds exactly what the exercise is meant to protect. It
never travels inside an exported document, and it is treated like the
rest of the case file.

## What is not verified

**The window.** `tests/test_gui_qt.py` builds it on Qt's offscreen
platform and drives it with clicks: the five screens, the help from
each, the refusals, the confirmations, the keyboard path. It has also
been run by hand on macOS (Python 3.14, PySide6 6.12). It has not been
run on Windows.

The release is built on Python 3.12, which is also the version both CI
jobs run, so 3.12 is the supported runtime and the one the executable
embeds. Development on 3.14 works and is what the macOS runs used; the
code targets 3.11 and above. Nothing in it depends on a version-specific
feature, and the suite passing on two versions is the only claim made. A segfault on quit was reported once on macOS and could
not be reproduced; the lazy type creation seen in its trace now happens
at import instead of at closing time, which is checked at startup, but
the crash itself is not proven gone.

**Word itself.** A document made by Word for Mac 16.114, with a header,
a footer, tracked changes and a comment, was passed through the window
and reopened in Word: no repair prompt, same layout, the reviewer's
name gone from the comment, the revisions, people.xml and the
properties; the return trip gave back the original. That is one
document on one version of Word. A name whose formatting changes in the
middle (half bold) comes back in the formatting of its first part.

**The Windows executable.** It is built, it starts, and `--self-check`
returns 0 on a clean Windows runner with no Python installed, in three
seconds. That proves the bundle is complete, which is where one-file
builds fail. It does not prove the window behaves: nobody has opened it
on Windows yet.

**The colours of the main button.** Fixed in the window's own stylesheet
rather than left to the platform, after macOS drew the default button
light grey on white, where it read as disabled. `tests/test_contraste.py`
computes the WCAG contrast of every painted state from the stylesheet
that ships, so legibility is a number rather than an opinion. What no
test here can say is whether Windows draws the rest of the window around
it the way macOS does.

**The signed build.** The executable is unsigned, so Windows will warn on
first launch. That needs a code-signing certificate, not a code change.

## Running CI

`tests` runs on every push, on Linux. The Windows job and the build cost
several times as much per minute and run only on a `v*` tag or a manual
dispatch:

```
gh workflow run ci -f full=true
git tag v0.1.0 && git push origin v0.1.0   # builds and attaches the exe
```
