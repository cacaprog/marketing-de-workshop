{#- Fase 2 — parâmetros da observabilidade num só lugar (pesquisa R2/R3/R7).
    As faixas padrão COPIAM VOLUME_BAND e DISTRIBUTION_BAND de src/agentready/observability.py
    (e stack/config/stack.yaml → observability.bands); o DAG pode passá-las por var. Se divergirem,
    `make parity` mostra a diferença. As vars podem chegar como string (o Cosmos renderiza XCom como
    texto e o conftest dos testes passa tudo entre aspas), por isso cada macro normaliza o tipo. -#}

{% macro obs_band(kind) -%}
    {%- set defaults = {'volume': [0.5, 1.5], 'distribution': [0.5, 2.0]} -%}
    {%- set bands = var('obs_bands', defaults) -%}
    {%- if bands is string -%}{%- set bands = fromyaml(bands) -%}{%- endif -%}
    {%- set band = bands.get(kind, defaults[kind]) -%}
    {{ return([band[0] | float, band[1] | float]) }}
{%- endmacro %}

{% macro obs_min_history() -%}
    {{ return(var('min_history', 7) | int) }}
{%- endmacro %}

{#- Disjuntor de distribuição (config/guardrails.yaml → observability.block_on_distribution_anomaly,
    ou o override da execução). Devolve um literal SQL: true | false. -#}
{% macro breaker_on() -%}
    {%- set v = var('block_on_distribution_anomaly', false) -%}
    {%- if v is string -%}{%- set v = v | trim | lower in ('true', '1', 'yes', 'sim', 'ligado') -%}{%- endif -%}
    {{ return('true' if v else 'false') }}
{%- endmacro %}

{#- Só para o teste breaker_model_error_stops_gold (FR-008a): força um erro de SQL no modelo de entrada
    do disjuntor. Nunca é ligado pelo DAG. -#}
{% macro obs_force_error() -%}
    {%- set v = var('obs_force_error', false) -%}
    {%- if v is string -%}{%- set v = v | trim | lower in ('true', '1') -%}{%- endif -%}
    {{ return(v) }}
{%- endmacro %}
