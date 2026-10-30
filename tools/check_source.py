"""Check source entrypoints, method guides, Markdown links and the runnable synthetic project."""
import ast
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def literal(path, name):
    for item in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in item.targets):
            return ast.literal_eval(item.value)
    raise ValueError(f"missing catalog {name}: {path}")


def check(root=ROOT):
    root = Path(root).resolve()
    app = root / "app"
    errors = []
    methods = literal(app / "scripts/method_router.py", "METHODS")
    routes = literal(app / "scripts/meta.py", "ROUTES")
    for name, (script, _) in routes.items():
        if not (app / "scripts" / script).is_file():
            errors.append(f"missing entry: {name}: {script}")
    for name, method in methods.items():
        if not (app / method["guide"]).is_file():
            errors.append(f"missing method guide: {name}: {method['guide']}")
        for script, _ in method["phases"].values():
            if not (app / "scripts" / script).is_file():
                errors.append(f"missing method phase: {script}")
    links = 0
    for path in root.rglob("*.md"):
        if ".git" in path.parts or "_local" in path.parts or path.is_relative_to(root / "packaging" / "customer_docs"):
            continue
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            target = unquote(target.strip("<>").split("#")[0])
            if not target or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            links += 1
            if not (path.parent / target).exists():
                errors.append(f"broken Markdown link: {path.relative_to(root)} -> {target}")
    project_path = app / "validation/project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    seen = set()
    references = 0
    path_keys = {"idea", "input", "records", "dedup", "decisions", "ledger", "source-effects", "effects",
                 "analysis", "protocol", "report-map", "confirmation", "source-methods", "retrieval", "counts",
                 "source-review", "corrections", "prior-effects", "rob-plan", "rob-ledger", "stats-dir", "prisma-dir",
                 "packet", "stats", "narrative"}
    for stage in project["stages"]:
        if not (app / "scripts" / stage["script"]).is_file():
            errors.append(f"missing fixture stage: {stage['script']}")
        for key, value in stage["args"].items():
            if key not in path_keys:
                continue
            references += 1
            if value.startswith("@"):
                if value[1:].split("/")[0] not in seen or ".." in Path(value[1:]).parts:
                    errors.append(f"invalid stage reference: {value}")
            else:
                resolved = Path(value.replace("{project_dir}", str(project_path.parent)))
                if not resolved.is_absolute():
                    resolved = project_path.parent / resolved
                if not resolved.is_file():
                    errors.append(f"missing fixture input: {value}")
        seen.add(stage["id"])
    manifest_path = root / "SOURCE-MANIFEST.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, item in manifest["files"].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                errors.append(f"source manifest mismatch: {name}")
    return dict(status="FAIL" if errors else "PASS", routes=len(routes), methods=len(methods),
                markdown_local_links=links, synthetic_input_references=references, errors=errors,
                network_used=False, runtime_included=False)


if __name__ == "__main__":
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(bool(result["errors"]))
