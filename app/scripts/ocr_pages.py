"""Inspect image-only PDF pages and optionally create non-final OCR word candidates.

The OCR engine is an explicit local executable. This module never downloads one.
OCR output is unreviewed source text, not a verified numeric extraction.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import fulltext_extract as fulltext
import literature as lit

PAGE_FIELDS=("record_id","source_document","file_path","source_sha256","page","selectable_chars",
             "image_coverage","classification","ocr_candidate","detected_method","source_locator",
             "image_reader_declared","external_ocr_declared","available_paths","review_status")
WORD_FIELDS=("record_id","source_document","source_sha256","page","word","confidence",
             "low_confidence","x0_pdf_pt","top_pdf_pt","x1_pdf_pt","bottom_pdf_pt",
             "rendered_page_sha256","detected_method","source_locator","engine_version","language","status")
NUMBER_FIELDS=("record_id","source_document","source_sha256","page","raw_token","parsed_number",
               "confidence","low_confidence","rendered_page_sha256","detected_method","suggested_location","status")
MAX_BYTES=25_000_000
MAX_PAGES=500
MAX_OCR_PAGES=20
SCALE=2.0


def fail(message):raise ValueError(message)
def load(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def private_pdf():
    private=Path(__file__).resolve().parents[1]/"method-python-library"
    if private.is_dir() and str(private) not in sys.path:sys.path.insert(0,str(private))
    try:import pdfplumber
    except ImportError:fail("PDF_READER_MISSING: prepare project-private pdfplumber")
    return pdfplumber


def inspect(records,documents,out,image_reader,external_ocr):
    pdfplumber=private_pdf()
    choices={"declared_available","declared_unavailable","unknown"}
    if image_reader not in choices or external_ocr not in choices:
        fail("reader capability must be declared_available, declared_unavailable or unknown")
    records=Path(records).resolve();documents=Path(documents).resolve();target=Path(out).resolve()
    catalog,_=lit.read_csv(records,["record_id","title"])
    ids={r["record_id"] for r in catalog}
    if len(ids)!=len(catalog):fail("repeated record_id in bibliography")
    docs,_=lit.read_csv(documents,fulltext.DOC_FIELDS)
    if not docs:fail("documents CSV is empty")
    rows=[];sources={};seen=set()
    for n,doc in enumerate(docs,2):
        if any(doc.get(k) is None for k in fulltext.DOC_FIELDS):fail(f"document row {n}: truncated CSV")
        if doc["format"].lower().strip()!="pdf":continue
        rid=doc["record_id"];name=doc["source_document"].strip()
        if rid not in ids or not name or (rid,name) in seen or not doc["rights_basis"].strip():
            fail(f"document row {n}: invalid record, source name or rights basis")
        seen.add((rid,name))
        path=Path(doc["file_path"]).expanduser().resolve()
        if not path.is_file() or path.suffix.lower()!=".pdf" or not 0<path.stat().st_size<=MAX_BYTES:
            fail(f"document row {n}: missing, non-PDF or oversized file")
        digest=lit.sha256(path);sources[str(path)]=digest
        try:
            with pdfplumber.open(path) as pdf:
                if not 0<len(pdf.pages)<=MAX_PAGES:fail(f"document row {n}: invalid page count")
                for page_no,page in enumerate(pdf.pages,1):
                    chars=len("".join((page.extract_text() or "").split()))
                    area=max(float(page.width)*float(page.height),1.0)
                    image_area=sum(max(0,float(im["x1"])-float(im["x0"])) *
                                   max(0,float(im["bottom"])-float(im["top"])) for im in page.images)
                    coverage=min(1.0,image_area/area)
                    candidate=chars<40 and coverage>=.30
                    classification=("IMAGE_ONLY_CANDIDATE" if chars==0 else "MIXED_LOW_TEXT_CANDIDATE") if candidate else \
                                   ("SELECTABLE_TEXT" if chars>=40 else "LOW_TEXT_MANUAL")
                    largest=max(page.images,key=lambda im:max(0,float(im["x1"])-float(im["x0"])) *
                                max(0,float(im["bottom"])-float(im["top"]))) if page.images else None
                    bbox=(f"image bbox ({float(largest['x0']):.1f}, {float(largest['top']):.1f}, "
                          f"{float(largest['x1']):.1f}, {float(largest['bottom']):.1f}) PDF pt") if largest else ""
                    locator=f"PDF page {page_no} "+(bbox if candidate else "selectable text layer" if chars>=40 else "low text; source check needed")
                    paths=(["TEXT_LAYER_SCAN"] if chars>=40 else ["USER_SUPPLIED_TEXT"])
                    if candidate and image_reader=="declared_available":paths.append("DECLARED_HOST_IMAGE_REVIEW")
                    if candidate and external_ocr=="declared_available":paths.append("DECLARED_EXTERNAL_OCR")
                    rows.append(dict(record_id=rid,source_document=name,file_path=str(path),source_sha256=digest,
                        page=page_no,selectable_chars=chars,image_coverage=f"{coverage:.4f}",
                        classification=classification,ocr_candidate=str(candidate).lower(),
                        detected_method="pdfplumber_text_probe" if chars>=40 else "pdfplumber_image_probe",
                        source_locator=locator,image_reader_declared=image_reader,external_ocr_declared=external_ocr,
                        available_paths=";".join(paths),review_status="PENDING_SOURCE_REVIEW"))
        except ValueError:raise
        except Exception as exc:fail(f"document row {n}: PDF inspection failed: {exc}")
    if not rows:fail("no PDF documents supplied")
    if target.exists():fail("output exists; use a fresh OCR inspection directory")
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ocr-inspect-",dir=target.parent) as tmp:
        stage=Path(tmp)/"result";stage.mkdir()
        lit.write_csv(stage/"ocr_pages.csv",PAGE_FIELDS,rows)
        receipt=dict(schema="meta-ocr-page-inspection-v1",status="IMAGE_PAGE_CANDIDATES_ONLY_NO_OCR",
            capability_basis="host image reading and external OCR are caller declarations, not detected or authenticated",
            image_reader_declared=image_reader,external_ocr_declared=external_ocr,
            records_path=str(records),records_sha256=lit.sha256(records),documents_path=str(documents),
            documents_sha256=lit.sha256(documents),source_bytes=sources,pages_sha256=lit.sha256(stage/"ocr_pages.csv"),
            page_count=len(rows),ocr_candidate_pages=sum(r["ocr_candidate"]=="true" for r in rows))
        (stage/"ocr_inspection.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,target)
    print(receipt["status"],receipt["ocr_candidate_pages"],"candidate pages",target)


def checked_inspection(folder):
    root=Path(folder).resolve();receipt=load(root/"ocr_inspection.json")
    if receipt.get("schema")!="meta-ocr-page-inspection-v1" or receipt.get("status")!="IMAGE_PAGE_CANDIDATES_ONLY_NO_OCR":
        fail("OCR inspection receipt invalid")
    for path,digest in ((receipt["records_path"],receipt["records_sha256"]),
                        (receipt["documents_path"],receipt["documents_sha256"]),
                        (root/"ocr_pages.csv",receipt["pages_sha256"]),*receipt["source_bytes"].items()):
        if not Path(path).is_file() or lit.sha256(path)!=digest:fail("OCR inspection source/output changed: "+str(path))
    pages,_=lit.read_csv(root/"ocr_pages.csv",PAGE_FIELDS)
    if len(pages)!=receipt["page_count"] or sum(r["ocr_candidate"]=="true" for r in pages)!=receipt["ocr_candidate_pages"]:
        fail("OCR page counts changed")
    if any(receipt["source_bytes"].get(r["file_path"])!=r["source_sha256"] for r in pages):
        fail("OCR page source identity changed")
    return root,receipt,pages


def recognize(inspection,adapter,engine,tessdata_dir,language,out):
    root,inspection_receipt,pages=checked_inspection(inspection)
    engine=Path(engine).resolve();models=Path(tessdata_dir).resolve();target=Path(out).resolve()
    if adapter!="tesseract_tsv":fail("OCR_ADAPTER_UNAVAILABLE: choose an implemented OCR adapter")
    if not engine.is_file():fail("OCR_ENGINE_MISSING: pass an existing explicit OCR executable path")
    if not language or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_+" for c in language.lower()):
        fail("OCR language code invalid")
    for lang in language.split("+"):
        if not (models/(lang+".traineddata")).is_file():
            fail("OCR_MODEL_MISSING: "+lang+".traineddata in explicit tessdata directory")
    candidates=[r for r in pages if r["ocr_candidate"]=="true"]
    if not candidates:fail("no image-only/low-text image pages to OCR")
    if len(candidates)>MAX_OCR_PAGES:fail("OCR candidate pages exceed 20-page per-run bound")
    if target.exists():fail("output exists; use a fresh OCR result directory")
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        version=subprocess.run([str(engine),"--version"],capture_output=True,text=True,timeout=10,check=True)
    except (OSError,subprocess.SubprocessError) as exc:fail("OCR_ENGINE_UNAVAILABLE: version check failed: "+str(exc))
    first=(version.stdout or version.stderr).splitlines()
    engine_version=first[0].strip() if first else ""
    if not engine_version.lower().startswith("tesseract "):fail("OCR_ENGINE_UNSUPPORTED: expected Tesseract version output")
    private=Path(__file__).resolve().parents[1]/"method-python-library"
    if private.is_dir() and str(private) not in sys.path:sys.path.insert(0,str(private))
    try:import pypdfium2 as pdfium
    except ImportError:fail("PDF_RENDERER_MISSING: prepare project-private pypdfium2")
    words=[];numbers=[]
    with tempfile.TemporaryDirectory(prefix=".ocr-page-images-",dir=target.parent) as tmp:
        for item in candidates:
            pdf=pdfium.PdfDocument(item["file_path"])
            page=pdf[int(item["page"])-1]
            image=Path(tmp)/("page-"+str(len(words))+"-"+item["page"]+".png")
            page.render(scale=SCALE).to_pil().save(image)
            image_sha=lit.sha256(image)
            args=[str(engine),str(image),"stdout","--tessdata-dir",str(models),"-l",language,"tsv"]
            try:result=subprocess.run(args,capture_output=True,text=True,timeout=90,check=True)
            except (OSError,subprocess.SubprocessError) as exc:fail("OCR_ENGINE_FAILED: "+str(exc))
            reader=csv.DictReader(result.stdout.splitlines(),delimiter="\t")
            required={"level","left","top","width","height","conf","text"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):fail("OCR_ENGINE_FAILED: invalid TSV output")
            for row in reader:
                if row["level"]!="5" or not row["text"].strip():continue
                try:
                    confidence=float(row["conf"]);left=float(row["left"]);top=float(row["top"])
                    width=float(row["width"]);height=float(row["height"])
                except (TypeError,ValueError):fail("OCR_ENGINE_FAILED: invalid word coordinate/confidence")
                if not 0<=confidence<=100 or min(left,top,width,height)<0:fail("OCR_ENGINE_FAILED: invalid word values")
                loc=f"page {item['page']} OCR bbox ({left/SCALE:.1f}, {top/SCALE:.1f}, {(left+width)/SCALE:.1f}, {(top+height)/SCALE:.1f}) PDF pt"
                word=dict(record_id=item["record_id"],source_document=item["source_document"],
                    source_sha256=item["source_sha256"],page=item["page"],word=row["text"][:250],
                    confidence=f"{confidence:.1f}",low_confidence=str(confidence<70).lower(),
                    x0_pdf_pt=f"{left/SCALE:.1f}",top_pdf_pt=f"{top/SCALE:.1f}",
                    x1_pdf_pt=f"{(left+width)/SCALE:.1f}",bottom_pdf_pt=f"{(top+height)/SCALE:.1f}",
                    rendered_page_sha256=image_sha,detected_method="external_ocr:tesseract_tsv",
                    source_locator=loc,engine_version=engine_version,language=language,
                    status="OCR_UNVERIFIED_REVIEW_REQUIRED")
                words.append(word)
                for match in fulltext.NUMBER.finditer(row["text"]):
                    numbers.append(dict(record_id=item["record_id"],source_document=item["source_document"],
                        source_sha256=item["source_sha256"],page=item["page"],raw_token=match.group(0),
                        parsed_number=str(fulltext.number(match.group("num"),"OCR candidate")),
                        confidence=f"{confidence:.1f}",low_confidence=str(confidence<70).lower(),
                        rendered_page_sha256=image_sha,detected_method="external_ocr:tesseract_tsv",
                        suggested_location=loc,status="OCR_UNVERIFIED_REVIEW_REQUIRED"))
    with tempfile.TemporaryDirectory(prefix=".ocr-result-",dir=target.parent) as tmp:
        stage=Path(tmp)/"result";stage.mkdir()
        lit.write_csv(stage/"ocr_words.csv",WORD_FIELDS,words)
        lit.write_csv(stage/"ocr_numeric_candidates.csv",NUMBER_FIELDS,numbers)
        receipt=dict(schema="meta-ocr-candidates-v1",status="OCR_UNVERIFIED_REVIEW_REQUIRED",final=False,
            inspection_path=str(root),inspection_sha256=lit.sha256(root/"ocr_inspection.json"),
            adapter=adapter,engine_path=str(engine),engine_sha256=lit.sha256(engine),engine_version=engine_version,
            language=language,model_hashes={lang:lit.sha256(models/(lang+".traineddata")) for lang in language.split("+")},
            words_sha256=lit.sha256(stage/"ocr_words.csv"),numbers_sha256=lit.sha256(stage/"ocr_numeric_candidates.csv"),
            word_count=len(words),numeric_candidate_count=len(numbers),low_confidence_word_count=sum(w["low_confidence"]=="true" for w in words),
            reviewed_by_human=False,semantic_value_verified=False)
        (stage/"ocr_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,target)
    print(receipt["status"],receipt["word_count"],"words",receipt["low_confidence_word_count"],"low confidence",target)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("inspect");p.add_argument("--records",required=True);p.add_argument("--documents",required=True)
    p.add_argument("--image-reader",choices=("declared_available","declared_unavailable","unknown"),default="unknown")
    p.add_argument("--external-ocr",choices=("declared_available","declared_unavailable","unknown"),default="unknown")
    p.add_argument("--out",required=True)
    p=sub.add_parser("recognize");p.add_argument("--inspection",required=True);p.add_argument("--adapter",required=True)
    p.add_argument("--engine",required=True)
    p.add_argument("--tessdata-dir",required=True);p.add_argument("--language",default="eng");p.add_argument("--out",required=True)
    p=sub.add_parser("verify");p.add_argument("--inspection",required=True)
    a=parser.parse_args()
    try:
        if a.command=="inspect":inspect(a.records,a.documents,a.out,a.image_reader,a.external_ocr)
        elif a.command=="recognize":recognize(a.inspection,a.adapter,a.engine,a.tessdata_dir,a.language,a.out)
        else:
            _,receipt,_=checked_inspection(a.inspection)
            print("OCR_INSPECTION_VERIFIED",receipt["page_count"],"pages")
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,csv.Error) as exc:
        parser.exit(2,"Validation: "+str(exc)+"\n")
