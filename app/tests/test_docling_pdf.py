"""Synthetic contract tests, not real-study accuracy evidence. No model/network needed."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import docling_pdf as adapter
import fulltext_extract as ft
import literature as lit


def fixture():
    prov = [{"page_no": 2, "bbox": {"l": 10, "t": 100, "r": 200, "b": 50, "coord_origin": "BOTTOMLEFT"}}]
    def cell(text, r, c, re=None, ce=None, **kwargs):
        return dict(text=text, start_row_offset_idx=r, end_row_offset_idx=re or r + 1,
                    start_col_offset_idx=c, end_col_offset_idx=ce or c + 1,
                    row_span=(re or r + 1)-r, col_span=(ce or c+1)-c,
                    bbox=prov[0]["bbox"], **kwargs)
    return {"body": {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/tables/0"}]},
            "texts": [{"self_ref": "#/texts/0", "label": "caption", "text": "SYNTHETIC Table 1: mean (SD), kg", "prov": prov}],
            "tables": [{"self_ref": "#/tables/0", "label": "table", "prov": prov,
                "captions": [{"$ref": "#/texts/0"}], "footnotes": [],
                "data": {"num_rows": 3, "num_cols": 3, "table_cells": [
                    cell("Group", 0, 0, re=2, column_header=True),
                    cell("Outcome <synthetic>", 0, 1, ce=3, column_header=True),
                    cell("Mean", 1, 1, column_header=True), cell("SD", 1, 2, column_header=True),
                    cell("Synthetic A", 2, 0, row_header=True), cell("20.5", 2, 1), cell("3.2", 2, 2)]}}]}


class Contract(unittest.TestCase):
    def test_spans_and_html_escape(self):
        view = adapter.table_html(fixture()["tables"][0])
        self.assertIn('rowspan="2"', view)
        self.assertIn('colspan="2"', view)
        self.assertIn("&lt;synthetic&gt;", view)
        self.assertEqual(view.count("<th "), 5)

    def test_provenance_header_and_missing_semantics(self):
        source = fixture()
        unchanged = copy.deepcopy(source)
        blocks, nums, cells = adapter.normalized(source, "SYN", "synthetic", "a" * 64, "DOC/document.json")
        self.assertEqual(source, unchanged)
        self.assertEqual(len(cells), 7)
        mean = next(n for n in nums if n["raw_token"] == "20.5")
        self.assertEqual(mean["page"], 2)
        self.assertIn("Mean", json.loads(mean["column_headers_json"]))
        self.assertIn("Synthetic A", json.loads(mean["row_headers_json"]))
        self.assertEqual(json.loads(mean["bbox_json"])["coord_origin"], "BOTTOMLEFT")
        self.assertIn("PENDING", mean["review_status"])
        self.assertEqual(mean["cell_id"], "#/tables/0/data/table_cells/5")
        self.assertNotIn("sd", mean)
        self.assertNotIn("se", mean)
        again = adapter.normalized(source, "SYN", "synthetic", "a"*64, "DOC/document.json")[1]
        self.assertEqual(nums, again)

    def test_multipage_does_not_guess_cell_page(self):
        raw = fixture()
        raw["tables"][0]["prov"].append({"page_no": 3, "bbox": {}})
        _, nums, _ = adapter.normalized(raw, "SYN", "synthetic", "a"*64, "DOC/document.json")
        n = next(n for n in nums if n["raw_token"] == "20.5")
        self.assertEqual(n["page"], "")
        self.assertIn("ambiguous pages", n["suggested_location"])

    def test_comma_and_bound_need_explicit_correction(self):
        raw = fixture()
        raw["texts"][0]["text"] = "SYNTHETIC p=1,000 and p<0.001 and MD \u22122.5"
        _, nums, _ = adapter.normalized(raw, "SYN", "synthetic", "a"*64, "DOC/document.json")
        self.assertEqual(next(n for n in nums if n["raw_token"] == "1,000")["numeric_ambiguity"], "COMMA_DECIMAL_OR_GROUPING")
        self.assertIn("BOUND_NOT_POINT_VALUE", next(n for n in nums if n["raw_token"] == "<0.001")["numeric_ambiguity"])
        self.assertEqual(next(n for n in nums if n["raw_token"] == "\u22122.5")["parsed_number"], "-2.5")

    def test_model_manifest_tamper_and_escape(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp:
            root = Path(temp)
            (root / "model.bin").write_bytes(b"synthetic model bytes")
            manifest = dict(schema="meta-docling-models-v1", files={"model.bin": lit.sha256(root / "model.bin")})
            adapter.dump(root / "model_manifest.json", manifest)
            adapter.model_manifest(root)
            (root / "model.bin").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "missing/changed"):
                adapter.model_manifest(root)
            manifest["files"] = {"../escape": "0"*64}
            adapter.dump(root / "model_manifest.json", manifest)
            with self.assertRaises(ValueError):
                adapter.model_manifest(root)


if __name__ == "__main__":
    unittest.main()
