"""Read-only scoped Night City v2 technical checks; never authorizes release."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain.night_case_simulation import SearchBudget, run_smoke_policy, validate_matrix
from domain.night_case_state import rules_snapshot
from domain.night_case_v2_format import compile_v2, load_v2


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate a Night City v2 case without publishing")
    parser.add_argument("case", type=Path)
    parser.add_argument("--scope", required=True, choices=("structure", "witness", "smoke"))
    parser.add_argument("--timezone", default="Europe/Berlin")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-commands", type=int, default=2000)
    parser.add_argument("--max-states", type=int, default=5000)
    parser.add_argument("--max-seconds", type=float, default=10.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = {"scope": args.scope, "scope_passed": False, "publishable": False,
              "checks": {"structure": "not_checked", "witness": "not_checked", "smoke": "not_checked",
                         "projections": "not_checked", "human_story": "not_checked", "database": "not_checked"}}
    try:
        budget = SearchBudget(args.max_commands, args.max_states, args.max_seconds)
        if args.seed < 0: raise ValueError("seed must be nonnegative")
        case = compile_v2(load_v2(args.case.read_bytes()))
        rules = rules_snapshot(args.timezone)
        report["case_id"] = case.case_id
        report["case_hash"] = case.content_hash
        report["rules_hash"] = rules.rules_hash
        report["checks"]["structure"] = "passed"
        if args.scope == "structure":
            report["scope_passed"] = True
        elif args.scope == "witness":
            matrix = validate_matrix(case, rules, seed=args.seed, budget=budget)
            report["checks"]["witness"] = "passed" if matrix.scope_passed else "not_checked"
            report["scope_passed"] = matrix.scope_passed
            report["assumptions"] = matrix.assumptions
            pairs = [(composition, variant["id"]) for variant in case.document()["variants"]
                     for composition in variant["composition_ids"]]
            report["matrix"] = [{"composition_id": composition, "variant_id": variant,
                                 "status": result.status, "reason": result.reason,
                                 "commands": result.commands, "states": result.states,
                                 "elapsed_seconds": result.elapsed_seconds,
                                 "search_elapsed_seconds": result.search_elapsed_seconds,
                                 "replay_elapsed_seconds": result.replay_elapsed_seconds,
                                 "budget_scope": result.budget_scope,
                                 "witness_schema": result.witness.document()["schema"] if result.witness else None,
                                 "trace_hash": result.witness.document()["trace_hash"] if result.witness else None}
                                for (composition, variant), result in zip(pairs, matrix.results)]
        else:
            cases = []
            for variant in case.document()["variants"]:
                for composition in variant["composition_ids"]:
                    for policy in ("passive_presence", "absent", "seeded_random"):
                        result = run_smoke_policy(case, rules, composition, variant["id"], policy=policy,
                                                  seed=args.seed, budget=budget)
                        cases.append({"composition_id": composition, "variant_id": variant["id"],
                                      "policy": policy, "status": result.status, "final_code": result.final_code,
                                      "passed": result.passed, "reason": result.reason,
                                      "commands": result.commands, "elapsed_seconds": result.elapsed_seconds})
            report["policies"] = cases
            report["scope_passed"] = bool(cases) and all(x["passed"] for x in cases)
            report["checks"]["smoke"] = "passed" if report["scope_passed"] else "not_checked"
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        report["checks"][args.scope] = "error"
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0 if report["scope_passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
