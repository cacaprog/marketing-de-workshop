# Contract: Policy evaluator and OPA decision API

## Shared module `src/agentready/policy.py`

```python
# illustrative signatures
@dataclass(frozen=True)
class Fatos: ...                      # fields in data-model.md §6

class Evaluator(Protocol):
    nome: str                          # "local" | "opa"
    def avaliar(self, acao: str, fatos: Fatos, limites: dict) -> Decisao: ...

@dataclass
class Decisao:
    permitido: bool
    checagens: list[tuple[str, bool, dict]]   # (id, ok, valores), today's order
    versao: str

def evaluator() -> Evaluator          # AGENTREADY_POLICY_EVALUATOR="module:Class" or LocalEvaluator
def describe(check_id, ok, valores, fatos, limites) -> str   # the pt-BR detail, byte-identical to today
def evaluate(acao, fatos) -> list[Check]                      # used by capabilities; never raises
```

- `acao` ∈ {`adjust_campaign_budget`, `pause_campaign`}. Budget checks are only for the first.
- `LocalEvaluator.avaliar`: today's comparisons from `_common_checks`/`budget_checks`, moved verbatim. If
  `campanha_existe` is false, it returns only that check (as today). `dados_frescos` is only evaluated when
  `limites.data.require_fresh_sources` is true (as today).
- `evaluate()` catches **every** evaluator exception and returns
  `[Check("politica_avaliada", False, "não foi possível avaliar a política: <motivo>")]` (fail closed).
- The policy version comes from `stack/policy/VERSION` when present. Otherwise it is `local-<guardrails.version>`,
  so the default track works without `stack/`. The stack's `OpaEvaluator` reports OPA's `versao`. Both equal the
  same `VERSION` file on the stack. Parity checks that.

## `capabilities.py` change (the only one)

`_common_checks` and `budget_checks` run the same queries as today, build `Fatos`, and return
`policy.evaluate(acao, fatos)`. The returned `(checks, camp, pct)` tuple, `_gate`, `_execute_approved` and the
span attribute names `preconditions` and `preconditions.failed` are unchanged. Two attributes are **added** to the
action span: `policy.evaluator` and `policy.version`.

## OPA decision API (stack)

`POST {OPA_URL}/v1/data/agentready/guardrails/decisao`

Request:
```json
{"input": {"acao": "adjust_campaign_budget",
           "fatos": {"campaign_id": "C01", "campanha_existe": true, "status": "active", "locked_by_human": false,
                     "objective": "conversion", "justificativa": "…", "frescor_status": "fresh",
                     "frescor_idade_h": 9.0, "orcamento_atual": 4000.0, "orcamento_novo": 4400.0,
                     "variacao_pct": 0.10, "soma_outras_ativas": 20000.0, "alteracoes_hoje": 0}}}
```

Response `200`:
```json
{"result": {"permitido": true, "versao": "1.0.0",
            "checagens": [{"id": "campanha_existe", "ok": true, "valores": {}},
                          {"id": "variacao_maxima", "ok": true, "valores": {"pct": 0.10, "limite": 0.20}}]}}
```

- The limits come from `data.guardrails` (the shared `config/guardrails.yaml`, loaded as data). Rego never
  hard-codes a limit.
- `OpaEvaluator`: 2 s timeout, no retries. It treats non-200, a missing `result`, or a response that fails the JSON
  schema (ids not in the known set, order differs from the local order list) as an error → `evaluate()` fails
  closed.

## Cases file `stack/policy/casos.yaml`

```yaml
- nome: variacao_acima_do_limite
  acao: adjust_campaign_budget
  fatos: {…, orcamento_atual: 4000, orcamento_novo: 5200, variacao_pct: 0.30}
  esperado_falhas: [variacao_maxima]
```

- `opa test stack/policy casos.yaml` (cases loaded as `data.casos`): `guardrails_test.rego` asserts that for each
  case the set of failed ids == `esperado_falhas`.
- `test_policy_equivalence.py` runs every case through `LocalEvaluator` and through OPA. Ids, verdicts, order and
  `describe()` text must be identical. It also asserts ≥ 1 passing and ≥ 1 failing case per check id.
- Mutation: for each numeric limit and list in a temp copy of `guardrails.yaml`, change it and assert that ≥ 1 case
  changes verdict (SC-006). OPA evaluates the copy in a **one-off** container (`docker compose run --rm opa eval …`
  with the copy as data). **Tests never write to the live `opa` service's data.**

## Preflight (stack)

`policy_opa.preflight()` runs at the start of `agente.executar`, before the ledger, whenever
`AGENTREADY_POLICY_EVALUATOR` is set. It calls `GET $OPA_URL/health?bundles` and a decision on a fixed probe input
(2 s timeout each), and validates the response schema. On failure it raises in pt-BR: `política indisponível ou
inválida: o agente não roda (falha fechada)`. The task fails and nothing executes. Per-action fail-closed still
covers OPA going down mid-run.

## Direct query (FR-017)

`agentready-stack politica <acao> <campanha> [<novo_orcamento>] [--justificativa T]` builds `Fatos` from the live
state with the same shared code, asks the configured evaluator, and prints a pt-BR table of checks plus
`PERMITIDO` / `NEGADO (variacao_maxima, …)`. Exit 0 if allowed, 3 if denied, 1 if the policy couldn't be
evaluated. It never executes anything.
