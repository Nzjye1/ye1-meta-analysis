"""Bounded PubMed E-utilities search with a local query and completeness ledger."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from literature import import_records
from types import SimpleNamespace


BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
RETRY_CODES = {429, 500, 502, 503, 504}
RECORD_FIELDS = ["source_record_id", "title", "authors", "year", "doi", "pmid"]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def plain(element):
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def article_year(article):
    for path in (".//JournalIssue/PubDate/Year", ".//ArticleDate/Year",
                 ".//JournalIssue/PubDate/MedlineDate", ".//PubmedData/History/PubMedPubDate/Year"):
        text = article.findtext(path) or ""
        match = re.search(r"(?:19|20)\d{2}", text)
        if match:
            return match.group()
    return ""


def parse_articles(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"invalid EFetch XML: {exc}") from exc
    if root.tag != "PubmedArticleSet" or root.find("ERROR") is not None:
        raise ValueError("EFetch was not a valid PubmedArticleSet")
    articles = []
    for entry in root:
        if entry.tag != "PubmedArticle":
            raise ValueError(f"unsupported PubMed entry type: {entry.tag}")
        pmid = (entry.findtext("./MedlineCitation/PMID") or "").strip()
        title = plain(entry.find("./MedlineCitation/Article/ArticleTitle"))
        year = article_year(entry)
        if not re.fullmatch(r"\d+", pmid) or not title or not year:
            raise ValueError(f"PubMed record {pmid or '?'} lacks PMID, title, or usable year")
        authors = []
        for author in entry.findall("./MedlineCitation/Article/AuthorList/Author"):
            name = " ".join(filter(None, (author.findtext("ForeName"), author.findtext("LastName"))))
            name = name or (author.findtext("CollectiveName") or "")
            if name:
                authors.append(name)
        doi = ""
        for identifier in entry.findall("./PubmedData/ArticleIdList/ArticleId"):
            if identifier.get("IdType", "").lower() == "doi":
                doi = (identifier.text or "").strip()
                break
        if not doi:
            for identifier in entry.findall("./MedlineCitation/Article/ELocationID"):
                if identifier.get("EIdType", "").lower() == "doi":
                    doi = (identifier.text or "").strip()
                    break
        articles.append(dict(source_record_id=pmid, title=title, authors="; ".join(authors),
                             year=year, doi=doi, pmid=pmid))
    return articles


class Client:
    def __init__(self, fixture=None):
        self.fixture = Path(fixture) if fixture else None
        self.last_call = 0.0
        self.requests = []

    def get(self, endpoint, params, filename, raw_dir, page=-1):
        if self.fixture:
            data = (self.fixture / filename).read_bytes()
            if len(data) > 8_000_000:
                raise ValueError("fixture response exceeds the per-request 8 MB cap")
            attempts = 0
            mode = "OFFLINE_FIXTURE"
        else:
            # One process stays below NCBI's no-key 3 requests/second ceiling.
            delay = 0.42 - (time.monotonic() - self.last_call)
            if delay > 0:
                time.sleep(delay)
            url = BASE + endpoint + "?" + urlencode(params)
            request = Request(url, headers={"User-Agent": "MetaAnalysisLocalSkill/0.1 (bounded literature search)"})
            attempts = 0
            while True:
                attempts += 1
                self.last_call = time.monotonic()
                try:
                    with urlopen(request, timeout=20) as response:
                        data = response.read(8_000_001)
                    if len(data) > 8_000_000:
                        raise ValueError("NCBI response exceeds the per-request 8 MB cap")
                    break
                except HTTPError as exc:
                    if exc.code not in RETRY_CODES or attempts >= 3:
                        raise
                    retry_after = exc.headers.get("Retry-After", "")
                    wait = int(retry_after) if retry_after.isdigit() else 2 ** (attempts - 1)
                    time.sleep(min(30, max(1, wait)))
                except (URLError, TimeoutError) as exc:
                    if isinstance(exc, URLError) and getattr(exc.reason, "winerror", None) == 10013:
                        raise  # local network permission denial is not a transient server error
                    if attempts >= 3:
                        raise
                    time.sleep(2 ** (attempts - 1))
            mode = "LIVE_NCBI"
        (raw_dir / filename).write_bytes(data)
        self.requests.append(dict(endpoint=endpoint, page=page, retstart=params.get("retstart", ""),
                                  retmax=params.get("retmax", ""), attempts=attempts, mode=mode,
                                  response_file=f"raw/{filename}", response_bytes=len(data),
                                  response_sha256=sha256(data), fetched_at_utc=utc_now()))
        return data


def write_table(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def validate(args):
    if not args.query.strip() or len(args.query) > 1000:
        raise ValueError("query must contain 1-1000 characters of public search terms")
    if not args.source_label.strip() or len(args.source_label) > 100:
        raise ValueError("source label must be nonblank and <=100 characters")
    if not 1 <= args.max_records <= 500 or not 1 <= args.page_size <= 100:
        raise ValueError("max-records must be 1-500 and page-size 1-100")
    if args.review_status == "human_reviewed" and not (args.reviewer and args.approval_ref):
        raise ValueError("human_reviewed requires reviewer and approval-ref")
    if args.review_status != "human_reviewed" and (args.reviewer or args.approval_ref):
        raise ValueError("reviewer and approval-ref require human_reviewed status")
    if args.pico and not Path(args.pico).is_file():
        raise ValueError("PICO path does not exist")
    if args.offline_fixture and not Path(args.offline_fixture).is_dir():
        raise ValueError("offline fixture directory does not exist")


def search(args):
    validate(args)
    target = Path(args.out)
    if target.exists():
        raise ValueError("output path already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pubmed-pending-", dir=target.parent) as temp:
        stage = Path(temp) / "result"
        stage.mkdir()
        raw_dir = stage / "raw"
        raw_dir.mkdir()
        client = Client(args.offline_fixture)
        query_receipt = dict(database="PubMed", endpoint=BASE, query=args.query,
            source_label=args.source_label, query_review_status=args.review_status,
            reviewer=args.reviewer or "", approval_ref=args.approval_ref or "",
            pico_file=str(Path(args.pico).resolve()) if args.pico else "",
            pico_sha256=sha256(Path(args.pico).read_bytes()) if args.pico else "",
            started_at_utc=utc_now(), max_records=args.max_records, page_size=args.page_size,
            mode="OFFLINE_FIXTURE" if args.offline_fixture else "LIVE_NCBI",
            disclaimer="Single-database bounded search; not an exhaustive systematic-review search")
        save_json(stage / "query_receipt.json", query_receipt)
        status = dict(status="FAILED", completeness="NOT_ESTABLISHED", retrieved=0,
                      database_count=None, query_translation="", query_review_status=args.review_status,
                      mode=query_receipt["mode"],
                      origin_authentication="NOT_INDEPENDENTLY_AUTHENTICATED", error="")
        try:
            esearch_params = dict(db="pubmed", term=args.query, retmax=0, retmode="json",
                                  usehistory="y", sort="pub date", tool="meta_analysis_local")
            data = client.get("esearch.fcgi", esearch_params, "esearch.json", raw_dir)
            response = json.loads(data)
            result = response.get("esearchresult", {})
            count = int(result["count"])
            if count < 0:
                raise ValueError("negative NCBI count")
            status["database_count"] = count
            status["query_translation"] = result.get("querytranslation", "")
            errors = result.get("errorlist") or {}
            if result.get("ERROR") or any(errors.values()):
                raise ValueError("NCBI reported a search error")
            total = min(count, args.max_records)
            collected = []
            if total:
                webenv, query_key = result.get("webenv"), result.get("querykey")
                if not webenv or not query_key:
                    raise ValueError("ESearch did not return WebEnv/querykey for snapshot paging")
                for page, start in enumerate(range(0, total, args.page_size)):
                    size = min(args.page_size, total - start)
                    params = dict(db="pubmed", query_key=query_key, WebEnv=webenv,
                                  retstart=start, retmax=size, retmode="xml", tool="meta_analysis_local")
                    xml = client.get("efetch.fcgi", params, f"efetch_{page:03d}.xml", raw_dir, page)
                    batch = parse_articles(xml)
                    if len(batch) != size:
                        raise ValueError(f"EFetch page {page} returned {len(batch)} of {size} requested records")
                    collected.extend(batch)
                    status["retrieved"] = len(collected)
                    write_table(stage / "retrieval_progress.csv", ["pmid", "efetch_page", "state"],
                                [dict(pmid=item["pmid"], efetch_page=i // args.page_size,
                                      state="PARTIAL_UNTIL_ALL_PAGES_PASS")
                                 for i, item in enumerate(collected)])
                ids = [item["pmid"] for item in collected]
                if len(ids) != len(set(ids)):
                    raise ValueError("duplicate PMID across EFetch pages")
                write_table(stage / "pubmed_export.csv", RECORD_FIELDS, collected)
                import_records(SimpleNamespace(input=str(stage / "pubmed_export.csv"),
                                               source=args.source_label, out=str(stage / "bibliography")))
                import_manifest = stage / "bibliography" / "import_manifest.csv"
                with import_manifest.open(encoding="utf-8", newline="") as handle:
                    import_rows = list(csv.DictReader(handle))
                for item in import_rows:
                    if item["key"] == "original_source_path":
                        item["value"] = str((target / "pubmed_export.csv").resolve())
                write_table(import_manifest, ["key", "value"], import_rows)
                with (stage / "bibliography" / "records.csv").open(encoding="utf-8", newline="") as handle:
                    record_ids = {row["pmid"]: row["record_id"] for row in csv.DictReader(handle)}
            else:
                write_table(stage / "pubmed_export.csv", RECORD_FIELDS, [])
                record_ids = {}
            write_table(stage / "result_ledger.csv",
                        ["pmid", "record_id", "source_label", "efetch_page", "raw_response_file"],
                        [dict(pmid=row["pmid"], record_id=record_ids[row["pmid"]],
                              source_label=args.source_label, efetch_page=i // args.page_size,
                              raw_response_file=f"raw/efetch_{i // args.page_size:03d}.xml")
                         for i, row in enumerate(collected)])
            status["retrieved"] = len(collected)
            status["completeness"] = (
                "FIXTURE_QUERY_COUNT_RECONCILED" if args.offline_fixture else
                "LIVE_QUERY_COUNT_RECONCILED_LOCAL_CLAIM") if total == count else (
                "FIXTURE_QUERY_LIMITED" if args.offline_fixture else "LIVE_QUERY_LIMITED")
            status["origin_authentication"] = "NOT_INDEPENDENTLY_AUTHENTICATED"
            status["status"] = "SUCCESS"
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
            status["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            status["finished_at_utc"] = utc_now()
            save_json(stage / "search_status.json", status)
            write_table(stage / "request_ledger.csv",
                        ["endpoint", "page", "retstart", "retmax", "attempts", "mode",
                         "response_file", "response_bytes", "response_sha256", "fetched_at_utc"], client.requests)
            if status["status"] == "SUCCESS" and (stage / "bibliography" / "records.csv").is_file():
                records_file = stage / "bibliography" / "records.csv"
                with records_file.open(encoding="utf-8", newline="") as handle:
                    imported = list(csv.DictReader(handle))
                for row in imported:
                    row["source_type"] = "pubmed_eutils"
                write_table(records_file, list(imported[0]), imported)
                save_json(stage / "bibliography" / "search_provenance.json", {
                    "schema": "meta-search-provenance-v1", "source_type": "pubmed_eutils",
                    "source_label": args.source_label, "search_root": "..",
                    "query_receipt_sha256": sha256((stage / "query_receipt.json").read_bytes()),
                    "search_status_sha256": sha256((stage / "search_status.json").read_bytes()),
                    "result_ledger_sha256": sha256((stage / "result_ledger.csv").read_bytes()),
                    "pubmed_export_sha256": sha256((stage / "pubmed_export.csv").read_bytes()),
                })
            write_table(stage / "search_manifest.csv", ["relative_path", "sha256", "bytes"],
                        [dict(relative_path=file.relative_to(stage).as_posix(),
                              sha256=sha256(file.read_bytes()), bytes=file.stat().st_size)
                         for file in sorted(stage.rglob("*")) if file.is_file()])
            os.replace(stage, target)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Public search terms only; never send patient data")
    parser.add_argument("--source-label", required=True, help="Stable label across reimports")
    parser.add_argument("--out", required=True, help="Fresh local output directory")
    parser.add_argument("--max-records", type=int, default=50)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--pico", help="Optional local PICO/protocol file; hash only, not transmitted")
    parser.add_argument("--review-status", choices=("pending_human_review", "human_reviewed"),
                        default="pending_human_review")
    parser.add_argument("--reviewer")
    parser.add_argument("--approval-ref")
    parser.add_argument("--offline-fixture", help="Directory with esearch.json and efetch_NNN.xml")
    args = parser.parse_args()
    try:
        result = search(args)
    except (OSError, ValueError) as exc:
        print(f"Validation: {exc}", file=sys.stderr)
        return 2
    print(f"{result['status']}: {result['retrieved']} records; {result['completeness']}; {args.out}")
    if result["status"] != "SUCCESS":
        print(result["error"], file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
