# Contract: Trace Parity Normalization (FR-010, research R7)

Input: each track's audit log, filtered to the agent run's `trace_id` and to the subtree rooted at `agent.run`.

| Kept | Dropped |
|---|---|
| `name`, path from `agent.run`, `status`, `status_message`, `attributes`, event names and attributes | `trace_id`, `span_id`, `parent_span_id`, `start_time`, `end_time`, event `time`, `hash`, `prev_hash` |

- **Key**: `agent.run/<ancestor names>/<name>#<campaign_id attribute, else ordinal among same-name siblings>`.
- **Value masking**: inside attribute and event values, the random identifiers the shared code generates with
  `uuid` (`CHG-<8 hex>`, `REQ-<8 hex>`, `capabilities._log_change` / `_queue`) become `CHG-*` / `REQ-*`. They are
  ids, like `span_id`, so they're dropped for the same reason. Found during implementation (T019).
- **Attribute exceptions**: none. Adding one requires a row here with the attribute, the reason it legitimately
  differs between tracks, and the spec reference. A new difference is a defect until explained (Principle I).
- **Live check** (Phoenix copy vs audit copy, `make test-live`) uses the same normalization, and additionally drops
  `openinference.*` attributes and resource attributes the collector adds, and the attributes Phoenix derives
  on ingest (`tool.name`, from `gen_ai.tool.name`; found in T038). Events are compared by name only, because
  Phoenix's GraphQL doesn't return event attributes.
