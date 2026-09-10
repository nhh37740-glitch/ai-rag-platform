from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "agent-server"))

from server import demo, vector_store  # noqa: E402
from core_contracts import RequestContext  # noqa: E402
from rag_core import retrieve  # noqa: E402


def main() -> None:
    dataset = json.loads(demo().body.decode("utf-8"))
    assert dataset["imported"] == 24, dataset
    assert dataset["question_count"] == 99, dataset

    result = retrieve(RequestContext("trace", "request"), "什么是静电感应？", vector_store, top_k=3)
    assert any("静电感应" in item.source_id for item in result.citations), result.citations
    print("SOURCE_RUNTIME_OK: CMRC2018 24 documents / 99 questions / retrieval hit")


if __name__ == "__main__":
    main()
