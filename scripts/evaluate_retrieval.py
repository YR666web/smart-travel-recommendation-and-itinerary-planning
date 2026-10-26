"""不调用在线模型的检索评测，输出命中率与逐题结果。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from app.rag.retriever import retrieve


def main() -> None:
    cases = json.loads(Path("evals/retrieval_cases.json").read_text(encoding="utf-8"))
    results = []
    for case in cases:
        start = time.monotonic()
        hits = retrieve(case["query"], top_k=5, content_type=case["content_type"], region=case["region"])
        sources = [hit.get("source_file") for hit in hits]
        results.append({"query": case["query"], "expected_file": case["expected_file"],
                        "hit_at_1": bool(sources) and sources[0] == case["expected_file"],
                        "hit_at_5": case["expected_file"] in sources,
                        "elapsed_ms": round((time.monotonic() - start) * 1000),
                        "sources": sources})
    count = len(cases)
    report = {"count": count,
              "hit_at_1": sum(r["hit_at_1"] for r in results) / count,
              "hit_at_5": sum(r["hit_at_5"] for r in results) / count,
              "results": results}
    output = Path("storage/evals")
    output.mkdir(parents=True, exist_ok=True)
    path = output / "retrieval-latest.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"hit@1={report['hit_at_1']:.1%}, hit@5={report['hit_at_5']:.1%}; report: {path}")


if __name__ == "__main__":
    main()
