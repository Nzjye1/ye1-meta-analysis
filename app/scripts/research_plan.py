"""Convert a structured customer idea into reviewable PICO and executable search candidates."""
import argparse
import json
from pathlib import Path
import tempfile
import os
import literature as lit


def prepare(source, output):
    idea = json.loads(Path(source).read_text(encoding="utf-8"))
    required = ("project_id", "question", "population", "intervention", "comparator",
                "outcome", "timepoint", "effect_type", "direction", "eligible_designs")
    if any(not idea.get(k) for k in required):
        lit.fail("idea requires " + ", ".join(required))
    if idea["effect_type"] not in {"RR", "OR", "HR", "MD", "SMD"}:
        lit.fail("unsupported effect type")
    if not isinstance(idea["eligible_designs"], list) or not all(isinstance(x, str) and x.strip() for x in idea["eligible_designs"]):
        lit.fail("eligible_designs must be a text list")
    concepts = idea.get("search_concepts")
    if not isinstance(concepts, list) or not concepts:
        lit.fail("search_concepts needs nonempty OR-term lists joined with AND")
    groups = []
    for terms in concepts:
        if not isinstance(terms, list) or not terms or any(not isinstance(t, str) or not t.strip() or
                any(c in t for c in '"[]\r\n') for t in terms):
            lit.fail("search terms must be nonempty plain phrases without quotes/brackets/newlines")
        groups.append("(" + " OR ".join('"' + t.strip() + '"[Title/Abstract]' for t in terms) + ")")
    protocol = dict(protocol_id=idea["project_id"], question=idea["question"],
        pico={k: idea[k] for k in ("population", "intervention", "comparator")},
        eligible_designs=idea["eligible_designs"],
        inclusion_criteria=idea.get("inclusion_criteria", ["PENDING user eligibility criteria"]),
        exclusion_criteria=idea.get("exclusion_criteria", ["PENDING user exclusion criteria"]),
        outcome=dict(name=idea["outcome"], timepoint=idea["timepoint"], effect_type=idea["effect_type"], direction=idea["direction"]),
        analysis=dict(contrast=idea.get("contrast", "intervention_vs_control"),
                      adjustment=idea.get("adjustment", "unadjusted"), model="RE", tau_method="REML", test="z", alpha=.05),
        sensitivity_plan=idea.get("sensitivity_plan", ["PENDING choose sensitivity plan"]),
        review_workflow_mode="PENDING_HUMAN_REVIEW",
        planning_status="PENDING_HUMAN_REVIEW")
    final = Path(output)
    if final.exists(): lit.fail("output already exists")
    final.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".idea-", dir=final.parent) as tmp:
        stage = Path(tmp) / "result"; stage.mkdir()
        (stage / "protocol_candidate.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")
        query = " AND ".join(groups)
        (stage / "search_candidate.json").write_text(json.dumps(dict(database="PubMed", query=query,
            query_review_status="pending_human_review", source_idea_sha256=lit.sha256(source),
            limitations=["Title/abstract terms only; MeSH, synonyms, limits and database coverage require human review",
                        "An executable query is not a validated comprehensive strategy" ]), indent=2), encoding="utf-8")
        lit.write_csv(stage / "analysis_candidate.csv", ["confirmed", "effect_type", "outcome", "timepoint", "contrast",
                      "adjustment", "model", "tau_method", "test", "alpha"],
            [dict(confirmed="NO", effect_type=idea["effect_type"], outcome=idea["outcome"], timepoint=idea["timepoint"], **protocol["analysis"])])
        (stage / "agent_tasks.md").write_text("# Research preparation\n\nReview the question, eligibility, effect direction, model and sensitivity plan with the customer. "
            "Expand synonyms and controlled vocabulary for each database; store full strategy, date and limits. "
            "Import permitted RIS/CSV locally. Obtain actual approval before freezing the protocol. "
            "All candidates are pending; no search, screening, source reading or approval has occurred.\n\nPubMed candidate:\n\n" + query + "\n", encoding="utf-8")
        os.replace(stage, final)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--idea", required=True); p.add_argument("--out", required=True)
    a = p.parse_args()
    try: prepare(a.idea, a.out)
    except (ValueError, OSError, KeyError, TypeError) as e: p.exit(2, f"Validation: {e}\n")
