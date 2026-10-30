"""Review-bound prose revision of an existing method Word draft; statistical facts stay locked."""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import literature as lit

W="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
ALLOWED={"Introduction","Discussion"}


def verify_draft(root):
    root=Path(root).resolve()
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    files=manifest.get("files")
    if not isinstance(files,dict) or not files:lit.fail("method draft needs a file manifest")
    actual={str(path.relative_to(root)).replace('\\','/') for path in root.rglob('*')
            if path.is_file() and path.name!='manifest.json'}
    if actual!=set(files):lit.fail("method draft manifest/member set differs")
    for name,digest in files.items():
        path=root/name
        if Path(name).is_absolute() or ".." in Path(name).parts or not path.is_file() or lit.sha256(path)!=digest:
            lit.fail("method draft member changed or missing: "+name)
    status=json.loads((root/"status.json").read_text(encoding="utf-8"))
    if status.get("final") is not False or not str(status.get("status","")).startswith("DRAFT_"):
        lit.fail("only non-final method draft can be revised")
    if not (root/"manuscript.docx").is_file() or not (root/"manuscript.md").is_file():
        lit.fail("method draft needs Word and Markdown manuscripts")
    return root,files,status


def markdown_replace(content,edits):
    for edit in edits:
        marker="## "+edit["section"]+"\n"
        if content.count(marker)!=1:lit.fail("draft section absent or repeated: "+edit["section"])
        start=content.index(marker)+len(marker)
        end=content.find("\n## ",start)
        if end<0:end=len(content)
        section=content[start:end]
        if section.count(edit["old_text"])!=1:lit.fail("old prose absent or repeated in Markdown section")
        content=content[:start]+section.replace(edit["old_text"],edit["new_text"],1)+content[end:]
    return content


def word_replace(source,target,edits):
    with zipfile.ZipFile(source) as archive:
        xml=ET.fromstring(archive.read("word/document.xml"))
        body=xml.find(W+"body");section="";counts=[0]*len(edits)
        for child in body:
            if child.tag!=W+"p":continue
            fragments=child.findall(".//"+W+"t")
            text="".join(part.text or "" for part in fragments)
            style=child.find("./"+W+"pPr/"+W+"pStyle")
            if style is not None and style.get(W+"val")=="Heading1":section=text
            for i,edit in enumerate(edits):
                if section==edit["section"] and text==edit["old_text"]:
                    if not fragments:lit.fail("Word paragraph has no text run")
                    fragments[0].text=edit["new_text"]
                    for part in fragments[1:]:part.text=""
                    counts[i]+=1
        if any(count!=1 for count in counts):lit.fail("old prose absent or repeated in Word section")
        with zipfile.ZipFile(target,"w") as result:
            for info in archive.infolist():
                data=ET.tostring(xml,encoding="utf-8",xml_declaration=True) if info.filename=="word/document.xml" else archive.read(info.filename)
                result.writestr(info,data)


def structured_replace(path,edits):
    if not path.is_file():return
    document=json.loads(path.read_text(encoding="utf-8"))
    sections=document.get("sections")
    if not isinstance(sections,list):lit.fail("method manuscript structure missing")
    current="";counts=[0]*len(edits)
    for paragraph in sections:
        if paragraph.get("style")=="Heading1":current=paragraph.get("text","")
        for i,edit in enumerate(edits):
            if current==edit["section"] and paragraph.get("text")==edit["old_text"]:
                paragraph["text"]=edit["new_text"];counts[i]+=1
    if any(count!=1 for count in counts):lit.fail("old prose absent or repeated in structured method manuscript")
    document["revision_status"]="PROSE_REVISED_REVIEW_PENDING"
    path.write_text(json.dumps(document,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def run(a):
    root,files,status=verify_draft(a.draft)
    changes=json.loads(Path(a.changes).read_text(encoding="utf-8"))
    if changes.get("schema")!="meta-method-prose-revision-v1" or \
            changes.get("prior_manifest_sha256")!=lit.sha256(root/"manifest.json") or \
            not all(isinstance(changes.get(key),str) and changes[key].strip() for key in ("reviewer","reason")):
        lit.fail("revision claim or prior draft hash missing/stale")
    edits=changes.get("edits")
    if not isinstance(edits,list) or not edits or len(edits)>30:lit.fail("1-30 prose edits required")
    seen=set()
    for edit in edits:
        if not isinstance(edit,dict) or edit.get("section") not in ALLOWED or \
                not all(isinstance(edit.get(key),str) and edit[key].strip() for key in ("old_text","new_text")) or \
                edit["old_text"]==edit["new_text"] or (edit["section"],edit["old_text"]) in seen:
            lit.fail("only distinct Introduction/Discussion prose replacements are accepted")
        seen.add((edit["section"],edit["old_text"]))
    out=Path(a.out).resolve()
    if out.exists():lit.fail("revision output exists")
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".method-revise-",dir=out.parent) as temp:
        stage=Path(temp)/"result"
        shutil.copytree(root,stage)
        content=markdown_replace((root/"manuscript.md").read_text(encoding="utf-8"),edits)
        word_replace(root/"manuscript.docx",stage/"manuscript.docx",edits)
        (stage/"manuscript.md").write_text(content,encoding="utf-8")
        structured_replace(stage/"manuscript.json",edits)
        status["revision_status"]="PROSE_REVISED_REVIEW_PENDING"
        status["word_visual_reviewed"]=False
        status["prior_draft_manifest_sha256"]=lit.sha256(root/"manifest.json")
        (stage/"status.json").write_text(json.dumps(status,indent=2)+"\n",encoding="utf-8")
        receipt=dict(schema="meta-method-prose-revision-receipt-v1",final=False,
                     prior_draft=str(root),prior_manifest_sha256=lit.sha256(root/"manifest.json"),
                     changes_sha256=lit.sha256(a.changes),reviewer=changes["reviewer"],reason=changes["reason"],
                     edited_sections=sorted({e["section"] for e in edits}),
                     numeric_methods_results_edited=False,scientific_claims_revalidated_by_software=False)
        (stage/"revision_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
        (stage/"attachment_index.json").write_text(json.dumps(dict(schema="meta-method-attachment-index-v1",
            files={name:digest for name,digest in files.items() if name not in {"manuscript.docx","manuscript.md","manuscript.json","status.json","manifest.json"}}),indent=2)+"\n",encoding="utf-8")
        (stage/"manifest.json").write_text(json.dumps(dict(files={str(p.relative_to(stage)).replace('\\','/'):lit.sha256(p)
            for p in stage.rglob('*') if p.is_file() and p.name!="manifest.json"}),indent=2)+"\n",encoding="utf-8")
        os.replace(stage,out)
    print(status["status"],"PROSE_REVISED_REVIEW_PENDING",out)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("draft","changes","out"):parser.add_argument("--"+key,required=True)
    args=parser.parse_args()
    try:run(args)
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile,ET.ParseError) as exc:
        parser.exit(2,"Validation: "+str(exc)+"\n")
