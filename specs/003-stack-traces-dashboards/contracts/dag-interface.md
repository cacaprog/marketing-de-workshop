# Contract: DAG Interface (Phase 3 delta)

Base: `specs/001-stack-production-track/contracts/dag-interface.md` and the Phase 2 delta.

- **No new params, tasks or dependencies.** The task graph is identical. Tracing is configuration plus spans
  emitted inside existing tasks.
- **`run_stack()`** (DAG file) injects the current W3C context as `TRACEPARENT` and removes
  `OTEL_SERVICE_NAME` from the subprocess environment.
- **Tag**: `stack-fase-2` → also `stack-fase-3`.
- **XCom of `agente.executar`**: adds `trace_url` (string or null). Every existing key is unchanged.
- **Approval form body**: adds the Phoenix link line (contracts/trace-links.md). Subject, options, defaults and
  timeout are unchanged.
- **`fechamento.marca_d_agua` return**: adds `traces: {ok, reason, url}`. It never raises because of traces.
- **Spans**: each existing task now produces the spans in [span-catalog.md](span-catalog.md).
- **Failure semantics unchanged**: no task fails because the collector or Phoenix is unavailable (FR-012).
