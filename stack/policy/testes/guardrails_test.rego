# Testes da política (Fase 4): cada caso de casos.yaml (carregado como data.casos) tem de falhar EXATAMENTE nas
# checagens esperadas. Rode: make politica-testes
package agentready.guardrails_test

import data.agentready.guardrails
import rego.v1

falhas(caso) := {c.id | some c in d.checagens; not c.ok} if {
	d := guardrails.decisao with input as {"acao": caso.acao, "fatos": caso.fatos}
}

test_cada_caso_falha_exatamente_no_esperado if {
	every caso in data.casos {
		falhas(caso) == {x | some x in caso.esperado_falhas}
	}
}

test_permitido_so_sem_falhas if {
	every caso in data.casos {
		d := guardrails.decisao with input as {"acao": caso.acao, "fatos": caso.fatos}
		d.permitido == (count(caso.esperado_falhas) == 0)
	}
}

test_cada_guardrail_tem_caso_que_passa_e_que_falha if {
	ids := {c.id | some caso in data.casos; d := guardrails.decisao with input as {"acao": caso.acao, "fatos": caso.fatos}; some c in d.checagens}
	every id in ids {
		some caso in data.casos
		id in caso.esperado_falhas
	}
	count(ids) == 10
}
