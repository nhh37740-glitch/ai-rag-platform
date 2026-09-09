from __future__ import annotations

import os
import sys

ART = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "artifacts", "observability", "0.1.0"))
sys.path.insert(0, ART)  # 让 "observability" 只从编译产物目录解析（该目录无 .py 源码）

from core_contracts import RequestContext  # noqa: E402
import observability  # noqa: E402

assert observability.__file__.endswith(".pyd"), f"expected compiled .pyd, got {observability.__file__}"
store = observability.make_trace_store()
with observability.Span(RequestContext("t", "r"), "x", store) as sp:
    pass
assert [e.span for e in store.get("t")] == ["x"]
print("imported_from   :", observability.__file__)
print("version         :", observability.__version__)
print("spans           :", [e.span for e in store.get("t")])
print("BINARY_DELIVERY_OK")
