"""Import a bounded UTF-8 RIS export through the existing CSV bibliography bridge."""
import argparse
import csv
import hashlib
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from literature import import_records


TAG = re.compile(r"^([A-Z0-9]{2})  - ?(.*)$")


def parse(text):
    records = []
    current = None
    entries = None
    last = None
    start = None
    for line_no, line in enumerate(text.splitlines(keepends=True), 1):
        plain = line.rstrip("\r\n")
        match = TAG.match(plain)
        if match:
            tag, value = match.groups()
            if tag == "TY":
                if current is not None:
                    raise ValueError(f"line {line_no}: TY before prior ER")
                current, entries, last, start = {}, [], None, line_no
            elif tag == "ER":
                if current is None:
                    raise ValueError(f"line {line_no}: ER without TY")
                records.append((start, line_no, current, entries))
                current, entries, last, start = None, None, None, None
                continue
            elif current is None:
                raise ValueError(f"line {line_no}: tag outside TY/ER record")
            current.setdefault(tag, []).append(value.strip())
            entries.append([tag, value.strip(), line_no])
            last = tag
        elif current is not None and plain.strip():
            if last is None:
                raise ValueError(f"line {line_no}: continuation without tag")
            current[last][-1] += " " + plain.strip()
            entries[-1][1] += " " + plain.strip()
        elif plain.strip():
            raise ValueError(f"line {line_no}: content outside TY/ER record")
    if current is not None:
        raise ValueError(f"line {start}: missing ER")
    if not records:
        raise ValueError("RIS has no TY/ER records")
    return records


def first(tags, *keys):
    return next((v for key in keys for v in tags.get(key, []) if v), "")


def normalize(rows):
    normalized, trace, tag_rows, ids = [], [], [], set()
    for start, end, tags, entries in rows:
        title = first(tags, "TI", "T1")
        year_raw = first(tags, "PY", "Y1", "DA")
        year_match = re.search(r"(?:19|20)\d{2}", year_raw)
        if not title or not year_match:
            raise ValueError(f"lines {start}-{end}: title (TI/T1) and year (PY/Y1/DA) required")
        explicit = first(tags, "ID")
        canonical = "\x1f".join((title, year_match.group(), ";".join(tags.get("AU", []) + tags.get("A1", []))))
        sid = explicit or "sha256-" + hashlib.sha256(canonical.encode()).hexdigest()[:20]
        if sid in ids:
            raise ValueError(f"lines {start}-{end}: repeated RIS source ID; adjudicate duplicate records before import")
        ids.add(sid)
        note = " ".join(tags.get("N1", []))
        pmid_match = re.search(r"\bPMID\s*[:=]\s*(\d+)\b", note, re.I)
        normalized.append({"source_record_id": sid, "title": title,
            "authors": "; ".join(tags.get("AU", []) + tags.get("A1", [])),
            "year": year_match.group(), "doi": first(tags, "DO"),
            "pmid": pmid_match.group(1) if pmid_match else ""})
        trace.append({"source_record_id": sid, "ris_start_line": start, "ris_end_line": end,
            "type": first(tags, "TY"), "journal": first(tags, "JF", "JO", "T2"),
            "abstract": "\n\n".join(value for tag, value, _ in entries if tag in ("AB", "N2")),
            "publisher_id": first(tags, "AN"), "raw_tag_count": len(entries)})
        tag_rows.extend({"source_record_id": sid, "occurrence": i, "line": line,
                         "tag": tag, "value": value}
                        for i, (tag, value, line) in enumerate(entries, 1))
    return normalized, trace, tag_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("input", "source", "out"):
        parser.add_argument(f"--{key}", required=True)
    a = parser.parse_args()
    target = Path(a.out)
    if target.exists():
        parser.error("output already exists")
    try:
        input_bytes = Path(a.input).read_bytes()
        text = input_bytes.decode("utf-8-sig")
        parsed = parse(text)
        rows, trace, tag_rows = normalize(parsed)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".ris-import-", dir=target.parent) as temp:
            temp_path = Path(temp)
            csv_path = temp_path / "normalized.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader(); writer.writerows(rows)
            imported = temp_path / "imported"
            import_records(SimpleNamespace(input=str(csv_path), source=a.source, out=str(imported)))
            with (imported / "ris_trace.csv").open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(trace[0]))
                writer.writeheader(); writer.writerows(trace)
            with (imported / "ris_tags.csv").open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(tag_rows[0]))
                writer.writeheader(); writer.writerows(tag_rows)
            shutil.copyfile(a.input, imported / "original_import.ris")
            # original_import.csv is the exact normalized bridge input.
            os.replace(imported, target)
        print(f"Imported {len(rows)} RIS records to {target}")
    except (UnicodeError, OSError, ValueError) as exc:
        print(f"Validation: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
