# Guardrails da Aurora como política (Fase 4, Bloco 3): QUEM decide se uma ação de escrita do agente pode acontecer.
#
# Os LIMITES não moram aqui: vêm de config/guardrails.yaml (compartilhado com a trilha padrão), carregado como
# data.guardrails. Os FATOS (estado vivo da campanha, frescor, portfólio, alterações do dia) chegam em input.fatos,
# lidos pelas capacidades do agente. A frase em pt-BR de cada checagem é montada fora daqui (agentready.policy.describe)
# — aqui só a decisão. As mesmas regras existem em Python (agentready.policy.LocalEvaluator, trilha padrão, sem rede):
# o teste de equivalência (stack/tests/test_policy_equivalence.py) e a paridade mantêm as duas iguais.
#
# Consulta: POST /v1/data/agentready/guardrails/decisao  {"input": {"acao": "...", "fatos": {...}}}
package agentready.guardrails

import rego.v1

# Mesma versão de stack/policy/VERSION (um teste confere).
versao := "1.0.0"

limites := data.guardrails

f := input.fatos

comuns := ["campanha_existe", "campanha_ativa", "sem_trava_humana", "objetivo_elegivel", "justificativa_presente"]

orcamento := ["variacao_maxima", "orcamento_minimo", "teto_do_portfolio", "limite_de_alteracoes"]

frescor := ["dados_frescos"] if limites.data.require_fresh_sources

else := []

de_orcamento := orcamento if input.acao == "adjust_campaign_budget"

else := []

# Campanha inexistente: só essa checagem (como sempre foi).
ids := ["campanha_existe"] if not f.campanha_existe

else := array.concat(array.concat(comuns, frescor), de_orcamento)

# ---------------------------------------------------------------------------------------------- regras

default justificativa_ok := false

justificativa_ok if {
	is_string(f.justificativa)
	trim_space(f.justificativa) != ""
}

default variacao_ok := false

variacao_ok if {
	is_number(f.variacao_pct)
	abs(f.variacao_pct) <= limites.budget.max_change_pct_per_action
}

ok := {
	"campanha_existe": f.campanha_existe == true,
	"campanha_ativa": f.status == "active",
	"sem_trava_humana": f.locked_by_human != true,
	"objetivo_elegivel": f.objective in limites.optimization.eligible_objectives,
	"justificativa_presente": justificativa_ok,
	"dados_frescos": f.frescor_status == "fresh",
	"variacao_maxima": variacao_ok,
	"orcamento_minimo": f.orcamento_novo >= limites.budget.min_daily_budget_brl,
	"teto_do_portfolio": f.portfolio_total <= limites.budget.portfolio_daily_cap_brl,
	"limite_de_alteracoes": f.alteracoes_hoje < limites.budget.max_changes_per_campaign_per_day,
} if input.acao == "adjust_campaign_budget"

else := {
	"campanha_existe": f.campanha_existe == true,
	"campanha_ativa": f.status == "active",
	"sem_trava_humana": f.locked_by_human != true,
	"objetivo_elegivel": f.objective in limites.optimization.eligible_objectives,
	"justificativa_presente": justificativa_ok,
	"dados_frescos": f.frescor_status == "fresh",
}

# Os números comparados (só para exibir; a frase pt-BR é montada fora da política).
valores := {
	"variacao_pct": f.variacao_pct,
	"limite_variacao": limites.budget.max_change_pct_per_action,
	"orcamento_novo": f.orcamento_novo,
	"minimo": limites.budget.min_daily_budget_brl,
	"portfolio_total": f.portfolio_total,
	"teto": limites.budget.portfolio_daily_cap_brl,
	"alteracoes_hoje": f.alteracoes_hoje,
	"max_alteracoes": limites.budget.max_changes_per_campaign_per_day,
}

checagens := [{"id": id, "ok": ok[id]} | some id in ids]

default permitido := false

permitido if {
	every c in checagens {
		c.ok
	}
}

decisao := {
	"permitido": permitido,
	"checagens": checagens,
	"versao": versao,
	"valores": valores,
}
