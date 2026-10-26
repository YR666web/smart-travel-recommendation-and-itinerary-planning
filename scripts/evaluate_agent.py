"""运行真实 Agent 评测；每个样本会调用模型并产生费用。"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.rag.embedder import embed

embed(["预热"])

from app.services.agent_service import PlanRequest, plan_trip  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12, help="执行前 N 个样本")
    args = parser.parse_args()
    cases = json.loads(Path("evals/trip_cases.json").read_text(encoding="utf-8"))[:args.limit]
    results = []
    for case in cases:
        try:
            run = plan_trip(PlanRequest.model_validate(case))
            plan = run["plan"]
            map_check = run.get("map_check", {})
            results.append({"case": case, "run_id": run["run_id"], "success": True,
                            "city_days_correct": plan["city"] == case["city"] and len(plan["days"]) == case["days"],
                            "has_citation": bool(plan["cited_sources"]),
                            "within_budget": plan["budget_total"] <= case["budget"],
                            "structured_places": all(day.get("places") for day in plan["days"]),
                            "map_status": map_check.get("status", "unavailable"),
                            "map_issue_count": len(map_check.get("issues", [])),
                            "checked_legs": sum(sum(leg["route"] is not None for leg in day["legs"])
                                                for day in map_check.get("days", [])),
                            "total_legs": sum(len(day["legs"]) for day in map_check.get("days", [])),
                            "tool_errors": sum(step["status"] == "error" for step in run["steps"]),
                            "elapsed_ms": run["elapsed_ms"], "usage": run["usage"]})
        except Exception as exc:
            results.append({"case": case, "success": False, "error": type(exc).__name__,
                            "reason": str(exc)[:300], "run_id": getattr(exc, "run_id", None)})
    report = {"evaluated_at": datetime.now().isoformat(), "cases": len(cases),
              "successful": sum(r["success"] for r in results), "results": results}
    completed = [r for r in results if r["success"]]
    report["metrics"] = {
        "completion_rate": len(completed) / len(cases) if cases else 0,
        "city_days_correct_rate": sum(r["city_days_correct"] for r in completed) / len(completed) if completed else 0,
        "citation_rate": sum(r["has_citation"] for r in completed) / len(completed) if completed else 0,
        "within_budget_rate": sum(r["within_budget"] for r in completed) / len(completed) if completed else 0,
        "structured_places_rate": sum(r["structured_places"] for r in completed) / len(completed) if completed else 0,
        "map_checked_rate": sum(r["map_status"] == "checked" for r in completed) / len(completed) if completed else 0,
        "route_coverage": (sum(r["checked_legs"] for r in completed) /
                           sum(r["total_legs"] for r in completed)) if sum(r["total_legs"] for r in completed) else None,
        "mean_latency_ms": round(sum(r["elapsed_ms"] for r in completed) / len(completed)) if completed else None,
        "mean_tokens": round(sum(r["usage"].get("prompt_tokens", 0) + r["usage"].get("completion_tokens", 0) for r in completed) / len(completed)) if completed else None,
    }
    output = Path("storage/evals")
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"agent-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{report['successful']}/{report['cases']} completed; report: {path}")
    print(json.dumps(report["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
