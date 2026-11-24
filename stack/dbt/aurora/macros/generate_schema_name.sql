{#- Os modelos caem EXATAMENTE nos schemas que o agente lê (silver, quarantine, meta, gold),
    sem o prefixo do target que o dbt colocaria por padrão. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ (custom_schema_name or target.schema) | trim }}
{%- endmacro %}
