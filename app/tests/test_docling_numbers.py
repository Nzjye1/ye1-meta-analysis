"""Lexical and confirmation regressions; synthetic inputs are not medical approvals."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import docling_numbers as numbers
import docling_pdf as adapter
import fulltext_extract as ft
import literature as lit


class NumericEvidence(unittest.TestCase):
    def test_atomic_commas_and_grouping_never_guessed(self):
        for text in ("0,09", "1,000", "1,234.56", "1.234,56", "0, 09", "1 234", "1\u202f234", "1'234"):
            with self.subTest(text=text):
                got = numbers.lexemes(text)
                self.assertEqual(len(got), 1)
                self.assertEqual(got[0]["raw_token"], text)
                self.assertEqual(got[0]["parsed_number"], "")
                self.assertTrue(got[0]["numeric_ambiguity"])

    def test_plain_decimal_and_scientific_normalization(self):
        for text, value in (("1.90", "1.90"), ("-2.5", "-2.5"), ("\u22122.5", "-2.5"),
                            ("1e-3", "0.001"), ("+0.09", "0.09"), ("1234", "1234")):
            with self.subTest(text=text):
                token = numbers.lexemes(text)[0]
                self.assertEqual(token["parsed_number"], value)
                self.assertEqual(token["numeric_ambiguity"], "")

    def test_malformed_composite_does_not_expose_acceptable_fragments(self):
        for text in ("0,,09", "1,234x2", "2.3.4", "3/abc", "abc0,09", "1.23.45kg"):
            with self.subTest(text=text):
                self.assertTrue(all(t["numeric_ambiguity"] for t in numbers.lexemes(text)))

    def test_bounds_ranges_pairs_and_unknowns_remain_unresolved(self):
        for text in ("<0.001", "\u22640.09", "0-6", "10.4\u2013169.8", "-2.5 to -1.0", "1.9 \u00b1 2.2",
                     "1.9 (0-6)", "1/2", "1:2", "12+34", "1 23", "1.2.3", "09", "7.2\ufffd", "~2.5"):
            with self.subTest(text=text):
                tokens = numbers.lexemes(text)
                self.assertTrue(tokens)
                self.assertTrue(all(t["numeric_ambiguity"] for t in tokens), tokens)
                self.assertTrue(all(not t["parsed_number"] for t in tokens))

    def vote(self, candidate, decision="accept", value="", reason=""):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp:
            path = Path(temp) / "review.csv"
            lit.write_csv(path, ft.REVIEW_FIELDS, [dict(effect_id="SYNTHETIC_ONLY", field="estimate",
                candidate_id="SYN-CAND", decision=decision, value=value, verified_location="page 1 table SYNTHETIC",
                reason=reason, reviewer="SYNTHETIC_TEST_NOT_APPROVAL", reviewed_at="2026-10-30")])
            return ft.review_rows(path, ft.REVIEW_FIELDS, "test", {("SYNTHETIC_ONLY", "estimate")},
                {"SYNTHETIC_ONLY": {"record_id": "SYN", "source_document": "SYN"}}, {"SYN-CAND": candidate})

    def candidate(self, text):
        return dict(numbers.lexemes(text)[0], context=text, extractor="docling_cpu_text_layer_candidate_only",
                    record_id="SYN", source_document="SYN", page="1", source_conflict_ids_json="[]")

    def test_comma_accept_blocked_explicit_interpretation_required(self):
        for text, values in (("0,09", ("0.09",)), ("1,000", ("1.000", "1000"))):
            candidate = self.candidate(text)
            with self.assertRaisesRegex(ValueError, "ambiguous numeric"):
                self.vote(candidate)
            with self.assertRaisesRegex(ValueError, "correction requires"):
                self.vote(candidate, "correct", values[0])
            for value in values:
                result, _ = self.vote(candidate, "correct", value, "Synthetic explicit locale interpretation, not a medical effect")
                self.assertEqual(result[("SYNTHETIC_ONLY", "estimate")]["value"], value)

    def test_fragment_cannot_be_accepted_or_corrected_as_complete_evidence(self):
        candidate = self.candidate("0,09")
        candidate.update(raw_token="09", parsed_number="9", numeric_ambiguity="", source_char_start="2",
                         normalization_rule="unicode-minus-and-decimal-dot")
        for decision in ("accept", "correct"):
            with self.assertRaisesRegex(ValueError, "complete source lexeme"):
                self.vote(candidate, decision, "9", "Synthetic probe")

    def test_flags_values_and_legacy_rows_are_revalidated(self):
        candidate = self.candidate("0,09")
        for changes in ({"numeric_ambiguity": ""}, {"parsed_number": "9"}, {"context": "09"}):
            with self.assertRaisesRegex(ValueError, "complete source lexeme"):
                self.vote(dict(candidate, **changes))
        with self.assertRaisesRegex(ValueError, "legacy Docling"):
            self.vote(dict(candidate, numeric_policy=""))
        normal = self.candidate("1.90")
        self.assertEqual(self.vote(normal)[0][("SYNTHETIC_ONLY", "estimate")]["value"], "1.90")

    def test_unresolved_source_conflict_blocks_accept_and_correct(self):
        candidate = self.candidate("11.8")
        candidate["source_conflict_ids_json"] = '["SYN-CONFLICT"]'
        for decision in ("accept", "correct"):
            with self.assertRaisesRegex(ValueError, "unresolved original-source conflict"):
                self.vote(candidate, decision, "1.8", "Not a medical resolution")

    def test_conflict_requires_actual_source_quote_and_pdf_hash(self):
        raw={"texts": [{"text": "SYN body SD 1.8", "prov": [{"page_no": 10}]}],
             "tables": [{"prov": [{"page_no": 11}], "data": {"table_cells": [{"text": "25.7 (\u00b111.8)"}]}}]}
        conflict=dict(conflict_id="SYN", record_id="SYN", source_document="SYN", source_sha256="a"*64,
            field="SD", left_ref="#/texts/0",left_quote="SD 1.8",right_ref="#/tables/0/data/table_cells/0",
            right_quote="11.8",reason="Synthetic unresolved disagreement")
        self.assertEqual(adapter.document_conflicts(raw,"SYN","SYN","a"*64,[conflict])[0]["resolution"], "")
        for change in ({"left_quote":"not present"}, {"source_sha256":"b"*64}):
            with self.assertRaises(ValueError):
                adapter.document_conflicts(raw,"SYN","SYN","a"*64,[dict(conflict,**change)])


if __name__ == "__main__":
    unittest.main()
