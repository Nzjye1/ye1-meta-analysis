"""Reconcile two separately supplied screening ledgers, with explicit third-party adjudication."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile

import literature as lit

VOTE_FIELDS = ("record_id", "stage", "decision", "reason", "reviewer", "decision_date")
ADJ_FIELDS = ("record_id", "stage", "decision", "reason", "adjudicator",
              "decision_date", "adjudication_reason")
STAGES = ("title_abstract", "full_text")
DECISIONS = {"include", "exclude", "pending"}
CANON_FIELDS = list(VOTE_FIELDS) + ["revision_of", "revision_reason"]


def date(value, label):
    try:
        return dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        lit.fail(f"{label}: YYYY-MM-DD date required")


def rows(path, fields, active, role):
    if path is None:
        return {}, None
    values, _ = lit.read_csv(path, fields, allow_empty=(role == "adjudicator"))
    found = {}
    identities = set()
    for i, row in enumerate(values, 2):
        if any(row.get(field) is None for field in fields):
            lit.fail(f"{role} row {i}: missing CSV cells")
        key = (row["record_id"], row["stage"])
        if key[0] not in active or key[1] not in STAGES or key in found:
            lit.fail(f"{role} row {i}: unknown/removed record, invalid stage, or repeated vote")
        if row["decision"] not in DECISIONS:
            lit.fail(f"{role} row {i}: invalid decision")
        identity = (row["adjudicator"] if role == "adjudicator" else row["reviewer"]).strip()
        if not identity:
            lit.fail(f"{role} row {i}: named reviewer required")
        identities.add(identity)
        date(row["decision_date"], f"{role} row {i}")
        if row["decision"] == "exclude" and not row["reason"].strip():
            lit.fail(f"{role} row {i}: exclusion reason required")
        if row["decision"] != "exclude" and row["reason"].strip():
            lit.fail(f"{role} row {i}: reason reserved for exclusion")
        if role == "adjudicator" and not row["adjudication_reason"].strip():
            lit.fail(f"adjudicator row {i}: conflict rationale required")
        found[key] = row
    if role == "adjudicator" and not values:
        return found, None
    if len(identities) != 1:
        lit.fail(f"{role}: exactly one stable reviewer name per file required")
    return found, next(iter(identities))


def changed(a, b):
    return a["decision"] != b["decision"] or (a["decision"] == "exclude" and
        " ".join(a["reason"].split()).casefold() != " ".join(b["reason"].split()).casefold())


def reconcile(records_path, dedup_path, a_path, b_path, adj_path=None):
    records, _ = lit.read_csv(records_path, ["record_id", "title", "year", "doi", "pmid"])
    dedup = lit.load_dedup(records, dedup_path)
    active = {rid for rid, item in dedup.items() if item["disposition"] == "keep"}
    a_votes, reviewer_a = rows(a_path, VOTE_FIELDS, active, "reviewer A")
    b_votes, reviewer_b = rows(b_path, VOTE_FIELDS, active, "reviewer B")
    if reviewer_a == reviewer_b:
        lit.fail("reviewer A and B must be distinct self-declared people")
    adj, adjudicator = rows(adj_path, ADJ_FIELDS, active, "adjudicator")
    if adjudicator is not None and adjudicator in {reviewer_a, reviewer_b}:
        lit.fail("adjudicator must differ from both primary reviewers")
    expected_title = {(rid, "title_abstract") for rid in active}
    missing = []
    for label, votes in (("A", a_votes), ("B", b_votes)):
        missing += [dict(record_id=rid, stage=stage, needed=f"reviewer_{label}")
                    for rid, stage in sorted(expected_title - set(votes))]
    final, audit, conflicts = {}, [], []
    used_adj = set()

    def resolve(key):
        left, right = a_votes.get(key), b_votes.get(key)
        if left is None or right is None:
            if left is None:
                missing.append(dict(record_id=key[0], stage=key[1], needed="reviewer_A"))
            if right is None:
                missing.append(dict(record_id=key[0], stage=key[1], needed="reviewer_B"))
            return None
        conflict = changed(left, right)
        third = adj.get(key)
        if conflict:
            conflicts.append(dict(record_id=key[0], stage=key[1],
                reviewer_a=reviewer_a, decision_a=left["decision"], reason_a=left["reason"], date_a=left["decision_date"],
                reviewer_b=reviewer_b, decision_b=right["decision"], reason_b=right["reason"], date_b=right["decision_date"],
                adjudicator=adjudicator if third else "",
                adjudication_reason=third["adjudication_reason"] if third else "",
                status="ADJUDICATED" if third else "UNRESOLVED"))
            if third is None:
                return None
            if date(third["decision_date"], "adjudication") < max(date(left["decision_date"], "vote A"),
                                                                     date(right["decision_date"], "vote B")):
                lit.fail(f"{key}: adjudication predates primary votes")
            used_adj.add(key)
            choice, who = third, adjudicator
        else:
            if third is not None:
                lit.fail(f"{key}: adjudication provided without disagreement")
            choice, who = left, f"dual:{reviewer_a}+{reviewer_b}"
        final[key] = dict(record_id=key[0], stage=key[1], decision=choice["decision"],
            reason=choice["reason"], reviewer=who,
            decision_date=max(left["decision_date"], right["decision_date"], choice["decision_date"]),
            revision_of="", revision_reason="")
        audit.append(dict(record_id=key[0], stage=key[1], reviewer_a=reviewer_a,
            decision_a=left["decision"], reason_a=left["reason"], date_a=left["decision_date"],
            reviewer_b=reviewer_b, decision_b=right["decision"], reason_b=right["reason"],
            date_b=right["decision_date"], adjudicator=adjudicator if conflict else "",
            adjudication_reason=third["adjudication_reason"] if conflict else "",
            final_decision=choice["decision"], final_reason=choice["reason"],
            final_date=final[key]["decision_date"]))
        return final[key]

    for rid in sorted(active):
        resolve((rid, "title_abstract")) if (rid, "title_abstract") in a_votes and (rid, "title_abstract") in b_votes else None
    required_full = {(rid, "full_text") for rid in active if final.get((rid, "title_abstract"), {}).get("decision") == "include"}
    supplied_full = {key for key in a_votes.keys() | b_votes.keys() if key[1] == "full_text"}
    if supplied_full - required_full:
        lit.fail("full-text votes require an agreed or adjudicated title/abstract inclusion")
    for key in sorted(required_full):
        resolve(key)
    if set(adj) != used_adj:
        lit.fail("adjudication has an unknown, premature, or unused conflict row")
    canonical = [final[key] for rid in sorted(active) for key in
                 ((rid, "title_abstract"), (rid, "full_text")) if key in final]
    ready = not missing and all(row["status"] == "ADJUDICATED" for row in conflicts)
    if ready:
        lit.validate_screening(records, canonical, active)
    pending = sum(row["decision"] == "pending" for row in canonical)
    status = "NEEDS_REVIEW" if missing else "NEEDS_ADJUDICATION" if not ready else (
             "READY_WITH_PENDING" if pending else "DUAL_SCREEN_READY")
    return dict(status=status, records=records, active=active, decisions=canonical,
                audit=audit, conflicts=conflicts, missing=missing,
                reviewer_a=reviewer_a, reviewer_b=reviewer_b, adjudicator=adjudicator,
                pending_decisions=pending)


def previous_attempt(output, a):
    """Validate an incomplete prior attempt before resuming with updated vote files."""
    if not output.is_dir():
        lit.fail("--resume requires an existing incomplete dual-screen directory")
    receipt_path = output / "dual_screen_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema") != "meta-dual-screen-v1" or receipt.get("status") not in {
            "NEEDS_REVIEW", "NEEDS_ADJUDICATION"} or (output / "decisions.csv").exists():
        lit.fail("--resume only accepts an incomplete dual-screen attempt without decisions")
    if receipt.get("review_mode") != a.mode:
        lit.fail("--resume review mode changed; start a new dossier")
    for name, path in (("records", a.records), ("dedup", a.dedup),
                       ("reviewer_a", a.reviewer_a), ("reviewer_b", a.reviewer_b)):
        item = receipt["inputs"][name]
        if str(Path(path).resolve()) != item["path"] or not Path(path).is_file():
            lit.fail(f"--resume source path changed: {name}")
        if name in {"records", "dedup"} and lit.sha256(path) != item["sha256"]:
            lit.fail(f"--resume bibliography/dedup changed: {name}; start a new dossier")
    expected = {"decision_audit.csv": "audit_sha256", "conflicts.csv": "conflicts_sha256",
                "missing_votes.csv": "missing_sha256", "status.json": "status_sha256"}
    if {p.name for p in output.iterdir()} != set(expected) | {"dual_screen_receipt.json"}:
        lit.fail("--resume prior attempt has unexpected or missing files")
    for name, key in expected.items():
        if lit.sha256(output / name) != receipt[key]:
            lit.fail(f"--resume prior audit changed: {name}")
    return receipt


def verify_provenance(records_path, dedup_path, decisions_path):
    folder = Path(decisions_path).resolve().parent
    path = folder / "dual_screen_receipt.json"
    if not path.is_file():
        return False
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schema") != "meta-dual-screen-v1" or receipt.get("status") not in {
            "DUAL_SCREEN_READY", "READY_WITH_PENDING"}:
        lit.fail("invalid dual-screen receipt")
    verify_prior_chain(receipt)
    supplied = {"records": records_path, "dedup": dedup_path,
                "reviewer_a": receipt["inputs"]["reviewer_a"]["path"],
                "reviewer_b": receipt["inputs"]["reviewer_b"]["path"]}
    if "adjudication" in receipt["inputs"]:
        supplied["adjudication"] = receipt["inputs"]["adjudication"]["path"]
    for key, value in supplied.items():
        item = receipt["inputs"][key]
        if str(Path(value).resolve()) != item["path"] or not Path(value).is_file() or lit.sha256(value) != item["sha256"]:
            lit.fail(f"dual-screen source changed: {key}")
    if (str(Path(decisions_path).resolve()) != receipt["decisions_path"] or
            lit.sha256(decisions_path) != receipt["decisions_sha256"]):
        lit.fail("dual-screen compiled decisions changed")
    for filename, key in (("decision_audit.csv", "audit_sha256"),
                          ("conflicts.csv", "conflicts_sha256"),
                          ("missing_votes.csv", "missing_sha256"),
                          ("status.json", "status_sha256")):
        item = folder / filename
        if not item.is_file() or lit.sha256(item) != receipt.get(key):
            lit.fail(f"dual-screen audit/status changed: {filename}")
    again = reconcile(supplied["records"], supplied["dedup"], supplied["reviewer_a"],
                      supplied["reviewer_b"], supplied.get("adjudication"))
    current, _ = lit.read_csv(decisions_path, CANON_FIELDS)
    if (again["status"] != receipt["status"] or
            any(row.get("decision_source") != "dual_screen_v1" for row in current) or
            any(row.get("screening_review_mode") != receipt.get("review_mode") for row in current) or
            [{key: row[key] for key in CANON_FIELDS} for row in current] != again["decisions"]):
        lit.fail("dual-screen decisions disagree with current reviewer/adjudication inputs")
    return True


def verify_prior_chain(receipt):
    seen = set()
    for _ in range(100):
        if not receipt.get("resumed_from_receipt_sha256"):
            return
        folder = Path(receipt["resumed_from_path"]).resolve()
        if folder in seen:
            lit.fail("cyclic dual-screen attempt history")
        seen.add(folder)
        prior = folder / "dual_screen_receipt.json"
        if not prior.is_file() or lit.sha256(prior) != receipt["resumed_from_receipt_sha256"]:
            lit.fail("prior dual-screen attempt changed or missing")
        receipt = json.loads(prior.read_text(encoding="utf-8"))
        if receipt.get("schema") != "meta-dual-screen-v1" or receipt.get("status") not in {
                "NEEDS_REVIEW", "NEEDS_ADJUDICATION"}:
            lit.fail("invalid prior dual-screen attempt")
        for name, key in (("decision_audit.csv", "audit_sha256"), ("conflicts.csv", "conflicts_sha256"),
                          ("missing_votes.csv", "missing_sha256"), ("status.json", "status_sha256")):
            path = folder / name
            if not path.is_file() or lit.sha256(path) != receipt.get(key):
                lit.fail(f"prior dual-screen audit changed: {name}")
    lit.fail("dual-screen attempt history exceeds 100 revisions")


def verify_if_marked(records_path, dedup_path, decisions_path):
    """Preserve manual CSV entry, but require evidence when a decision file claims dual review."""
    _, fields = lit.read_csv(decisions_path, VOTE_FIELDS)
    receipt = Path(decisions_path).resolve().parent / "dual_screen_receipt.json"
    if "decision_source" in fields or receipt.exists():
        if not receipt.is_file() or not dedup_path:
            lit.fail("dual-screen decisions require their receipt and dedup ledger")
        verify_provenance(records_path, dedup_path, decisions_path)


def write(a):
    output = Path(a.out).resolve()
    if output.exists() and not a.resume:
        lit.fail("output exists; preserve earlier screening evidence and use a fresh directory")
    prior = previous_attempt(output, a) if a.resume else None
    backup = None
    if prior:
        attempt = 1
        while True:
            backup = output.with_name(output.name + f".prior-{attempt:04d}")
            if not backup.exists():
                break
            attempt += 1
    if a.mode == "formal_dual" and (a.reviewer_a_role != "human_attested" or
                                     a.reviewer_b_role != "human_attested" or
                                     a.adjudication and a.adjudicator_role != "human_attested"):
        lit.fail("formal_dual requires explicit human_attested roles for both reviewers and any adjudicator")
    result = reconcile(a.records, a.dedup, a.reviewer_a, a.reviewer_b, a.adjudication)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dual-screen-", dir=output.parent) as tmp:
        stage = Path(tmp) / "result"
        stage.mkdir()
        audit_fields = ["record_id", "stage", "reviewer_a", "decision_a", "reason_a", "date_a",
                        "reviewer_b", "decision_b", "reason_b", "date_b", "adjudicator",
                        "adjudication_reason", "final_decision", "final_reason", "final_date"]
        conflict_fields = ["record_id", "stage", "reviewer_a", "decision_a", "reason_a", "date_a",
                           "reviewer_b", "decision_b", "reason_b", "date_b", "adjudicator",
                           "adjudication_reason", "status"]
        lit.write_csv(stage / "decision_audit.csv", audit_fields, result["audit"])
        lit.write_csv(stage / "conflicts.csv", conflict_fields, result["conflicts"])
        lit.write_csv(stage / "missing_votes.csv", ["record_id", "stage", "needed"], result["missing"])
        (stage / "status.json").write_text(json.dumps({
            "status": result["status"], "active_records": len(result["active"]),
            "conflicts": len(result["conflicts"]), "unresolved_conflicts": sum(x["status"] == "UNRESOLVED" for x in result["conflicts"]),
            "missing_votes": len(result["missing"]), "pending_decisions": result["pending_decisions"],
            "identity_authenticated": False, "independent_blinding_authenticated": False,
            "review_mode": a.mode,
            "reviewer_roles_attested": {"A": a.reviewer_a_role, "B": a.reviewer_b_role,
                                        "adjudicator": a.adjudicator_role if a.adjudication else None},
            "meaning": "Two separately supplied self-labeled vote files; roles, human identity, and blinding are not authenticated"
        }, indent=2) + "\n", encoding="utf-8")
        if result["status"] in {"DUAL_SCREEN_READY", "READY_WITH_PENDING"}:
            lit.write_csv(stage / "decisions.csv", CANON_FIELDS + ["decision_source", "screening_review_mode"],
                          [{**row, "decision_source": "dual_screen_v1", "screening_review_mode": a.mode}
                           for row in result["decisions"]])
        inputs = {key: {"path": str(Path(path).resolve()), "sha256": lit.sha256(path)}
                  for key, path in (("records", a.records), ("dedup", a.dedup),
                                    ("reviewer_a", a.reviewer_a), ("reviewer_b", a.reviewer_b))}
        if a.adjudication:
            inputs["adjudication"] = {"path": str(Path(a.adjudication).resolve()), "sha256": lit.sha256(a.adjudication)}
        (stage / "dual_screen_receipt.json").write_text(json.dumps({
            "schema": "meta-dual-screen-v1", "status": result["status"], "inputs": inputs,
            "decisions_path": str(output / "decisions.csv") if (stage / "decisions.csv").exists() else None,
            "decisions_sha256": lit.sha256(stage / "decisions.csv") if (stage / "decisions.csv").exists() else None,
            "audit_sha256": lit.sha256(stage / "decision_audit.csv"),
            "conflicts_sha256": lit.sha256(stage / "conflicts.csv"),
            "missing_sha256": lit.sha256(stage / "missing_votes.csv"),
            "status_sha256": lit.sha256(stage / "status.json"),
            "review_mode": a.mode,
            "reviewer_roles_attested": {"A": a.reviewer_a_role, "B": a.reviewer_b_role,
                                        "adjudicator": a.adjudicator_role if a.adjudication else None},
            "resumed_from_receipt_sha256": lit.sha256(output / "dual_screen_receipt.json") if prior else None,
            "resumed_from_path": str(backup) if prior else None,
            "identity_authenticated": False, "independent_blinding_authenticated": False
        }, indent=2) + "\n", encoding="utf-8")
        if prior:
            os.replace(output, backup)
            try:
                os.replace(stage, output)
            except OSError:
                os.replace(backup, output)
                raise
        else:
            if output.exists():
                lit.fail("output appeared during commit")
            os.replace(stage, output)
    print(f"{result['status']}: {len(result['active'])} active records; {len(result['conflicts'])} conflicts; {output}")
    return 0 if result["status"] in {"DUAL_SCREEN_READY", "READY_WITH_PENDING"} else 2


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for option in ("records", "dedup", "reviewer-a", "reviewer-b", "out"):
        p.add_argument("--" + option, required=True)
    p.add_argument("--adjudication")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--mode", choices=("exploratory_pair", "formal_dual"), default="exploratory_pair")
    for role in ("reviewer-a-role", "reviewer-b-role", "adjudicator-role"):
        p.add_argument("--" + role, choices=("unspecified", "human_attested", "agent_assisted", "ai_simulated"),
                       default="unspecified")
    args = p.parse_args()
    try:
        sys.exit(write(args))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        p.exit(2, f"Validation: {exc}\n")
