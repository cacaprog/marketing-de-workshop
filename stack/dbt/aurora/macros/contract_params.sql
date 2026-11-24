{#- Parâmetros do contrato lidos de meta.contract_registry em tempo de execução.
    O registro é construído a partir dos arquivos ODCS: nada é copiado para o dbt. -#}
{% macro contract_param(contract, field) -%}
  {%- if execute -%}
    {%- set r = run_query("select " ~ field ~ " from " ~ ref('contract_registry') ~ " where contract = '" ~ contract ~ "'") -%}
    {{ r.columns[0].values()[0] }}
  {%- else -%}
    null
  {%- endif -%}
{%- endmacro %}

{#- Verdadeiro quando a Bronze não tem alguma coluna do contrato (quebra de esquema). -#}
{% macro schema_broken(contract) -%}
  (select len(missing_columns) > 0 from {{ ref('contract_registry') }} where contract = '{{ contract }}')
{%- endmacro %}

{#- Mantém o conteúdo anterior da tabela quando o contrato está quebrado (pesquisa R6). -#}
{% macro keep_previous_if_broken(contract) -%}
  {%- set existing = adapter.get_relation(this.database, this.schema, this.identifier) -%}
  {%- if existing is not none %}
  union all
  select * from {{ this }} where {{ schema_broken(contract) }}
  {%- endif %}
{%- endmacro %}
