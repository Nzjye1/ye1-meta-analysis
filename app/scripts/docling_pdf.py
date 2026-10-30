"""Optional CPU Docling PDF adapter. Local files and unverified candidates only."""
import argparse
import datetime as dt
import hashlib
import html
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import time

import fulltext_extract as ft
import literature as lit
import docling_numbers as numeric

STATUS = "CANDIDATES_ONLY_NOT_VERIFIED"
NUM_FIELDS = ["candidate_id", "record_id", "source_document", "source_sha256", "page", "line",
              "token", "raw_token", "parsed_number", "unit_suffix", "suggested_location", "context", "extractor",
              "block_id", "table_id", "cell_id", "bbox_json", "provenance_json", "row_start", "row_end",
              "column_start", "column_end", "row_headers_json", "column_headers_json", "caption_refs_json",
              "footnote_refs_json", "context_block_refs_json", "local_document_json", "numeric_ambiguity",
              *numeric.FIELDS, "source_conflict_ids_json", "review_status"]
SEM_FIELDS = ["candidate_id", "record_id", "source_document", "study_id", "cohort_id", "group", "outcome",
              "timepoint", "unit", "statistic_kind", "n", "events", "mean", "sd", "se", "value",
              "raw_evidence", "source_location", "semantic_review_status"]


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compact(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def model_manifest(root):
    root = Path(root).resolve()
    receipt_path = root / "model_manifest.json"
    manifest = json.loads(receipt_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "meta-docling-models-v1" or not manifest.get("files"):
        raise ValueError("prepare the explicit local Docling model manifest first")
    for name, expected in manifest["files"].items():
        file = (root / name).resolve()
        if not file.is_relative_to(root) or not file.is_file() or lit.sha256(file) != expected:
            raise ValueError("local Docling model missing/changed: " + name)
    return manifest, lit.sha256(receipt_path)


def converter(models, threads):
    # Offline flags affect this worker only, never system security/network configuration.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    options = PdfPipelineOptions(artifacts_path=Path(models))
    options.do_ocr = False
    options.do_table_structure = True
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.table_structure_options.do_cell_matching = True
    options.enable_remote_services = False
    options.allow_external_plugins = False
    options.accelerator_options = AcceleratorOptions(num_threads=threads, device=AcceleratorDevice.CPU)
    return DocumentConverter(allowed_formats=[InputFormat.PDF], format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


def table_html(table):
    """Readable view with spans. Full original table data remains authoritative."""
    data = table["data"]
    cells = data.get("table_cells", [])
    starts = {(c["start_row_offset_idx"], c["start_col_offset_idx"]): c for c in cells}
    covered = {(r, col) for c in cells for r in range(c["start_row_offset_idx"], c["end_row_offset_idx"])
               for col in range(c["start_col_offset_idx"], c["end_col_offset_idx"])}
    lines = ['<!doctype html><meta charset="utf-8"><title>Unverified table</title>',
             '<style>table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:6px;white-space:pre-wrap}</style>',
             '<p>Unverified Docling table; inspect original PDF, captions, footnotes and units.</p><table>']
    for r in range(data["num_rows"]):
        lines.append("<tr>")
        for col in range(data["num_cols"]):
            c = starts.get((r, col))
            if c:
                tag = "th" if c.get("column_header") or c.get("row_header") else "td"
                rs = c["end_row_offset_idx"] - r
                cs = c["end_col_offset_idx"] - col
                lines.append(f'<{tag} rowspan="{rs}" colspan="{cs}">{html.escape(c.get("text", ""))}</{tag}>')
            elif (r, col) not in covered:
                lines.append("<td></td>")
        lines.append("</tr>")
    return "\n".join(lines + ["</table>"])


def normalized(raw, rid, name, digest, json_path):
    """Retain original provenance; no inferred statistic, group, unit or timepoint."""
    blocks, nums, table_cells = [], [], []
    lookup = {item["self_ref"]: item for key in ("texts", "tables", "pictures") for item in raw.get(key, [])}
    ordered = []
    seen = set()

    def visit(node):
        ref = node.get("$ref")
        if ref:
            if ref in seen:
                return
            seen.add(ref)
            node = lookup.get(ref, {})
            if not node:
                try:
                    key, index = ref.removeprefix("#/").split("/")
                    node = raw[key][int(index)]
                except (ValueError, KeyError, IndexError):
                    return
            if ref in lookup:
                ordered.append(node)
        for child in node.get("children", []):
            visit(child)

    visit(raw.get("body", {}))
    for item in lookup.values():
        if item["self_ref"] not in seen:
            ordered.append(item)
    for item in ordered:
        blocks.append({"block_id": item["self_ref"], "label": item.get("label"),
                       "text": item.get("text", ""), "prov": item.get("prov", []),
                       "captions": item.get("captions", []), "footnotes": item.get("footnotes", [])})

    def tokens(text, item, cell=None, cell_index=None):
        prov = item.get("prov", [])
        pages = sorted({p["page_no"] for p in prov})
        page = pages[0] if len(pages) == 1 else ""
        block_id = item["self_ref"]
        table_id = block_id if "data" in item else ""
        cell_id = f"{table_id}/data/table_cells/{cell_index}" if cell is not None else ""
        bbox = cell.get("bbox") if cell is not None else (prov[0].get("bbox") if len(prov) == 1 else None)
        bbox = bbox or None
        headers = item.get("data", {}).get("table_cells", [])
        row_headers, column_headers = [], []
        if cell is not None:
            row_headers = [c["text"] for c in headers if c.get("row_header") and
                           c["start_row_offset_idx"] < cell["end_row_offset_idx"] and
                           c["end_row_offset_idx"] > cell["start_row_offset_idx"]]
            column_headers = [c["text"] for c in headers if c.get("column_header") and
                              c["start_col_offset_idx"] < cell["end_col_offset_idx"] and
                              c["end_col_offset_idx"] > cell["start_col_offset_idx"]]
        nearby = [b["block_id"] for b in blocks if b["block_id"] != block_id and
                  any(p.get("page_no") in pages for p in b["prov"])]
        locator = f"page {page} {block_id}" if page else f"ambiguous pages {pages} {block_id}"
        if cell_id:
            locator += " " + cell_id
        if bbox:
            locator += " bbox " + compact(bbox)
        for i, lexeme in enumerate(numeric.lexemes(text), 1):
            key = compact([numeric.POLICY, digest, rid, name, block_id, cell_id,
                           lexeme["source_char_start"], lexeme["source_char_end"], lexeme["raw_token"]])
            nums.append(dict(candidate_id="NUM-" + hashlib.sha256(key.encode()).hexdigest()[:20],
                record_id=rid, source_document=name, source_sha256=digest, page=page, line="", token=i,
                **lexeme, suggested_location=locator, context=text,
                extractor="docling_cpu_text_layer_candidate_only", block_id=block_id, table_id=table_id,
                cell_id=cell_id, bbox_json=compact(bbox), provenance_json=compact(prov),
                row_start=cell["start_row_offset_idx"] if cell is not None else "",
                row_end=cell["end_row_offset_idx"] if cell is not None else "",
                column_start=cell["start_col_offset_idx"] if cell is not None else "",
                column_end=cell["end_col_offset_idx"] if cell is not None else "",
                row_headers_json=compact(row_headers), column_headers_json=compact(column_headers),
                caption_refs_json=compact(item.get("captions", [])), footnote_refs_json=compact(item.get("footnotes", [])),
                context_block_refs_json=compact(nearby), local_document_json=json_path,
                source_conflict_ids_json="[]",
                review_status="PENDING_MEDICAL_SEMANTIC_AND_SOURCE_REVIEW"))

    for item in ordered:
        if "data" in item and "table_cells" in item["data"]:
            for i, cell in enumerate(item["data"]["table_cells"]):
                table_cells.append({"table_id": item["self_ref"], "cell_id": f'{item["self_ref"]}/data/table_cells/{i}',
                                    "prov": item.get("prov", []), **cell})
                tokens(cell.get("text", ""), item, cell, i)
        elif item.get("text"):
            tokens(item["text"], item)
    return blocks, nums, table_cells


CONFLICT_FIELDS = ["conflict_id", "record_id", "source_document", "source_sha256", "field",
                   "left_ref", "left_quote", "right_ref", "right_quote", "reason"]


def conflict_inputs(path):
    rows = lit.read_csv(path, CONFLICT_FIELDS)[0] if path else []
    if len({r["conflict_id"] for r in rows}) != len(rows) or any(
            not all(r.get(k, "").strip() for k in CONFLICT_FIELDS) for r in rows):
        raise ValueError("source conflicts need distinct IDs and complete original-source anchors")
    return rows


def source_node(raw, ref):
    if not ref.startswith(("#/texts/", "#/tables/")):
        raise ValueError("source conflict ref must identify an original text block/table cell")
    node = raw
    for part in ref[2:].split("/"):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def document_conflicts(raw, rid, name, digest, rows):
    result = []
    for row in rows:
        if (row["record_id"], row["source_document"]) != (rid, name):
            continue
        if row["source_sha256"] != digest:
            raise ValueError("source conflict belongs to different original PDF bytes")
        item = dict(row, status="UNRESOLVED_ORIGINAL_SOURCE_DISAGREEMENT", resolution="")
        for side in ("left", "right"):
            node = source_node(raw, row[side + "_ref"])
            text = node.get("text", "")
            if row[side + "_quote"] not in text:
                raise ValueError("source conflict quotation absent from its original anchor")
            prov = node.get("prov")
            if prov is None and row[side + "_ref"].startswith("#/tables/"):
                prov = raw["tables"][int(row[side + "_ref"].split("/")[2])].get("prov", [])
            item[side + "_original_text"] = text
            item[side + "_provenance"] = prov or []
        result.append(item)
    return result


def apply_conflicts(candidates, conflicts):
    for candidate in candidates:
        ref = candidate["cell_id"] or candidate["block_id"]
        ids = sorted(c["conflict_id"] for c in conflicts if ref in (c["left_ref"], c["right_ref"]))
        candidate["source_conflict_ids_json"] = compact(ids)
        if ids:
            candidate["review_status"] = "HOLD_ORIGINAL_SOURCE_CONFLICT"


def check_numeric_evidence(folder, receipt, docs, candidates):
    """Regenerate candidates from immutable structured source, not editable CSV flags."""
    if receipt.get("docling_numeric_policy") != numeric.POLICY:
        raise ValueError("legacy Docling numeric evidence; rescan local PDFs with the current adapter")
    conflict_path = receipt.get("source_conflicts_path")
    if conflict_path and lit.sha256(conflict_path) != receipt.get("source_conflicts_input_sha256"):
        raise ValueError("original-source conflict input changed")
    rows = conflict_inputs(conflict_path)
    expected, conflicts = [], []
    for doc in docs:
        relative = doc["local_document_json"]
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder) or relative not in receipt["docling_artifacts_sha256"]:
            raise ValueError("Docling document JSON absent from bound evidence")
        raw = json.loads(path.read_text(encoding="utf-8"))
        _, numbers, _ = normalized(raw, doc["record_id"], doc["source_document"], doc["source_sha256"], relative)
        current = document_conflicts(raw, doc["record_id"], doc["source_document"], doc["source_sha256"], rows)
        apply_conflicts(numbers, current)
        expected.extend(numbers)
        conflicts.extend(current)
    if len(conflicts) != len(rows):
        raise ValueError("source conflict refers to a document absent from the scan")
    expected_rows = [{k: str(row.get(k, "")) for k in NUM_FIELDS} for row in expected]
    if candidates != expected_rows:
        raise ValueError("Docling numeric candidates differ from complete source lexemes/normalization evidence")
    saved = json.loads((folder / "source_conflicts.json").read_text(encoding="utf-8"))
    if saved != conflicts:
        raise ValueError("original-source conflict evidence differs from anchored quotations")


def scan(a):
    out = Path(a.out).resolve()
    if out.exists():
        raise ValueError("output exists; choose a fresh directory")
    records, _ = lit.read_csv(a.records, ["record_id", "title"])
    ids = {r["record_id"] for r in records}
    if len(ids) != len(records):
        raise ValueError("duplicate bibliography record_id")
    docs, _ = lit.read_csv(a.documents, ft.DOC_FIELDS)
    if len(docs) > 3:
        raise ValueError("small local adapter accepts at most three PDFs per call")
    used, inputs = set(), []
    for row in docs:
        if any(row.get(field) is None for field in ft.DOC_FIELDS):
            raise ValueError("document CSV row has missing cells")
        key = row["record_id"], row["source_document"]
        path = Path(row["file_path"]).expanduser().resolve()
        if key in used or key[0] not in ids or not key[1].strip() or not row["rights_basis"].strip():
            raise ValueError("unknown/duplicate document or missing rights basis")
        if row["format"].lower() != "pdf" or path.suffix.lower() != ".pdf" or not path.is_file():
            raise ValueError("Docling adapter requires local registered PDF files")
        if not 0 < path.stat().st_size <= 25_000_000:
            raise ValueError("PDF size must be 1 to 25,000,000 bytes")
        with path.open("rb") as stream:
            if not stream.read(5).startswith(b"%PDF-"):
                raise ValueError("invalid PDF header")
        used.add(key)
        inputs.append((row, path, lit.sha256(path)))
    manifest, model_hash = model_manifest(a.models)
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    engine = converter(a.models, a.threads)
    conflict_rows = conflict_inputs(getattr(a, "source_conflicts", None))
    catalog, candidates, semantics, metrics, warnings, conflicts = [], [], [], [], [], []
    with tempfile.TemporaryDirectory(prefix=".docling-", dir=out.parent) as temp:
        stage = Path(temp) / "result"
        stage.mkdir()
        for row, path, digest in inputs:
            mark = time.perf_counter()
            # Explicit local file, never URL. OCR intentionally disabled for this selectable-text pilot.
            result = engine.convert(path, raises_on_error=True, max_num_pages=500, max_file_size=25_000_000)
            if result.status.value != "success":
                raise ValueError("Docling conversion incomplete: " + result.status.value)
            doc = result.document
            raw = doc.export_to_dict()
            key = "DOC-" + hashlib.sha256(compact([digest, row["record_id"], row["source_document"]]).encode()).hexdigest()[:20]
            dest = stage / key
            dest.mkdir()
            dump(dest / "document.json", raw)
            (dest / "document.md").write_text(doc.export_to_markdown(), encoding="utf-8")
            relative_json = key + "/document.json"
            blocks, nums, cells = normalized(raw, row["record_id"], row["source_document"], digest, relative_json)
            current = document_conflicts(raw, row["record_id"], row["source_document"], digest, conflict_rows)
            apply_conflicts(nums, current)
            conflicts.extend(current)
            dump(dest / "blocks.json", blocks)
            dump(dest / "table_cells.json", cells)
            (dest / "document.txt").write_text("\n\n".join(
                f'[{b["block_id"]} pages {sorted({p["page_no"] for p in b["prov"]})}]\n{b["text"]}'
                for b in blocks), encoding="utf-8")
            tables = raw.get("tables", [])
            for i, table in enumerate(tables):
                dump(dest / f"table-{i}.json", table)
                (dest / f"table-{i}.html").write_text(table_html(table), encoding="utf-8")
                warnings.append({"record_id": row["record_id"], "table_id": table["self_ref"],
                    "reason": "TABLE_HEADER_FOOTNOTE_UNIT_AND_CROSS_PAGE_RELATION_REQUIRE_SOURCE_REVIEW"})
            catalog.append(dict(**{k: row[k] for k in ft.DOC_FIELDS if k != "file_path"},
                file_path=str(path), source_sha256=digest, page_count=len(doc.pages), bytes=path.stat().st_size,
                extraction_engine="docling " + metadata.version("docling"), local_document_json=relative_json))
            candidates.extend(nums)
            for n in nums:
                semantics.append(dict(candidate_id=n["candidate_id"], record_id=n["record_id"],
                    source_document=n["source_document"], raw_evidence=n["context"],
                    source_location=n["suggested_location"], semantic_review_status=(
                        "HOLD_ORIGINAL_SOURCE_CONFLICT" if n["source_conflict_ids_json"] != "[]" else "pending")))
            metrics.append({"record_id": row["record_id"], "physical_pages": len(doc.pages), "tables": len(tables),
                            "numeric_candidates": len(nums), "conversion_and_export_seconds": time.perf_counter() - mark})
            if lit.sha256(path) != digest:
                raise ValueError("source changed during conversion")
        if len(candidates) > 10_000:
            raise ValueError("candidate count exceeds 10,000; split the batch")
        if len(conflicts) != len(conflict_rows):
            raise ValueError("source conflict refers to a document absent from the scan")
        dump(stage / "source_conflicts.json", conflicts)
        warnings.extend(dict(record_id=c["record_id"], conflict_id=c["conflict_id"],
                             reason="HOLD_ORIGINAL_SOURCE_CONFLICT", evidence="source_conflicts.json") for c in conflicts)
        lit.write_csv(stage / "documents.csv", list(catalog[0]), catalog)
        lit.write_csv(stage / "numeric_candidates.csv", NUM_FIELDS, candidates)
        lit.write_csv(stage / "semantic_candidates.csv", SEM_FIELDS, semantics)
        dump(stage / "review_warnings.json", warnings)
        packages = [{"name": d.metadata["Name"], "version": d.version,
                     "license": d.metadata.get("License-Expression") or d.metadata.get("License", ""),
                     "project_urls": d.metadata.get_all("Project-URL", [])} for d in metadata.distributions()]
        dump(stage / "runtime_packages.json", packages)
        import psutil
        memory = psutil.Process().memory_info()
        hashes = {str(p.relative_to(stage)).replace("\\", "/"): lit.sha256(p) for p in stage.rglob("*") if p.is_file()}
        receipt = dict(schema="meta-fulltext-scan-v1", pdf_reader="docling_cpu", status=STATUS,
            docling_numeric_policy=numeric.POLICY,
            source_conflicts_path=str(Path(a.source_conflicts).resolve()) if getattr(a, "source_conflicts", None) else None,
            source_conflicts_input_sha256=lit.sha256(a.source_conflicts) if getattr(a, "source_conflicts", None) else None,
            created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            records_path=str(Path(a.records).resolve()), records_sha256=lit.sha256(a.records),
            input_documents_path=str(Path(a.documents).resolve()), input_documents_sha256=lit.sha256(a.documents),
            documents_sha256=hashes["documents.csv"], candidates_sha256=hashes["numeric_candidates.csv"],
            docling_artifacts_sha256=hashes, models_path=str(Path(a.models).resolve()), model_manifest_sha256=model_hash,
            model_sources=manifest.get("sources", []), metrics=metrics, wall_seconds=time.perf_counter() - started,
            cpu_threads=a.threads, ocr_enabled=False, remote_services_enabled=False,
            python_version=platform.python_version(), platform=platform.platform(),
            peak_working_set_bytes=getattr(memory, "peak_wset", None), working_set_bytes=memory.rss,
            document_count=len(catalog), candidate_count=len(candidates),
            table_indices_are_published_numbers=False,
            bbox_contract="Docling PDF points with explicit coord_origin; page_no is 1-based physical PDF page",
            scope="Text-layer PDF pilot only; all values and semantic mappings pending; no statistical derivation")
        dump(stage / "scan_receipt.json", receipt)
        os.replace(stage, out)
    print(f"{STATUS}: {len(catalog)} PDFs, {len(candidates)} numeric candidates; {out}")


def verify(a):
    receipt, _, _ = ft.checked_scan(a.scan)
    if receipt.get("pdf_reader") != "docling_cpu":
        raise ValueError("not a Docling scan")
    print(STATUS + ": source and artifact hashes checked")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("scan")
    for opt in ("records", "documents", "models", "out"):
        s.add_argument("--" + opt, required=True)
    s.add_argument("--threads", type=int, choices=range(1, 17), default=4)
    s.add_argument("--source-conflicts", help="optional locally reviewed, PDF-hash-bound source disagreements CSV")
    s.set_defaults(func=scan)
    v = sub.add_parser("verify")
    v.add_argument("--scan", required=True)
    v.set_defaults(func=verify)
    a = parser.parse_args()
    try:
        a.func(a)
    except (OSError, ValueError, KeyError, RuntimeError, ImportError) as exc:
        parser.exit(2, f"Docling adapter: {exc}\n")


if __name__ == "__main__":
    main()
