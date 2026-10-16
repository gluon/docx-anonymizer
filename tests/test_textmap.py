"""The run-splitting problem, in isolation."""

from __future__ import annotations

import unittest

from dxanon import textmap
from dxanon.textmap import Edit

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def document(*runs: str) -> object:
    body = "".join(f"<w:r><w:t>{run}</w:t></w:r>" for run in runs)
    return textmap.parse(f"<w:document {W}><w:body><w:p>{body}</w:p></w:body></w:document>".encode())


class SplitRuns(unittest.TestCase):
    def test_a_word_split_across_three_runs_reads_as_one_string(self):
        root = document("Jean DUP", "ONT", " a saisi")
        self.assertEqual(textmap.full_text(root), "Jean DUPONT a saisi")

    def test_replacement_spanning_runs_lands_in_the_first_one(self):
        root = document("Jean DUP", "ONT", " a saisi")
        paragraph = textmap.paragraphs(root)[0]
        start = paragraph.text.index("DUPONT")
        paragraph.apply([Edit(start, start + len("DUPONT"), "MARTIN")])

        self.assertEqual(textmap.full_text(root), "Jean MARTIN a saisi")
        nodes = list(root.iter(textmap.T))
        self.assertEqual(nodes[0].text, "Jean MARTIN")
        self.assertEqual(nodes[1].text, "")
        self.assertEqual(nodes[2].text, " a saisi")

    def test_untouched_runs_are_not_rewritten(self):
        root = document("Jean DUP", "ONT", " a saisi")
        paragraph = textmap.paragraphs(root)[0]
        changed = paragraph.apply([Edit(0, 4, "Marc")])
        self.assertEqual(changed, 1)

    def test_whitespace_only_result_gains_the_preserve_attribute(self):
        root = document("Monsieur DUPONT")
        paragraph = textmap.paragraphs(root)[0]
        paragraph.apply([Edit(9, 15, "")])
        node = next(root.iter(textmap.T))
        self.assertEqual(node.text, "Monsieur ")
        self.assertEqual(node.get(textmap.SPACE), "preserve")

    def test_overlapping_edits_are_rejected(self):
        paragraph = textmap.paragraphs(document("abcdef"))[0]
        with self.assertRaises(ValueError):
            paragraph.apply([Edit(0, 4, "x"), Edit(2, 6, "y")])

    def test_several_edits_in_one_paragraph_keep_their_offsets(self):
        root = document("A puis B puis C")
        paragraph = textmap.paragraphs(root)[0]
        paragraph.apply([Edit(0, 1, "XXXX"), Edit(7, 8, "Y"), Edit(14, 15, "ZZ")])
        self.assertEqual(textmap.full_text(root), "XXXX puis Y puis ZZ")


class TextBoxes(unittest.TestCase):
    def test_a_nested_paragraph_is_read_once_not_twice(self):
        xml = (
            f"<w:document {W}><w:body><w:p><w:r><w:t>Avant</w:t></w:r>"
            "<w:txbxContent><w:p><w:r><w:t>Dedans</w:t></w:r></w:p></w:txbxContent>"
            "</w:p></w:body></w:document>"
        )
        root = textmap.parse(xml.encode())
        self.assertEqual(sorted(p.text for p in textmap.paragraphs(root)), ["Avant", "Dedans"])


if __name__ == "__main__":
    unittest.main()
