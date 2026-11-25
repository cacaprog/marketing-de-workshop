{#- Teste de VEREDITO (Fase 2): falha quando algum alvo do pilar tem status 'fail'.
    'warn' (histórico insuficiente, pesquisa R7) passa: aviso nunca bloqueia nem vira erro.
    Roda só na tarefa folha observabilidade.testes (fica fora do build padrão: selectors.yml). -#}
{% test observability_check_passes(model) %}
select pillar, target, detail
from {{ model }}
where status = 'fail'
{% endtest %}
