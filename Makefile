.PHONY: install setup demo test mcp clean
install:        ## instala dependências
	uv sync --extra dev
setup:          ## gera o cenário e roda o pipeline (rode no dia do workshop)
	uv run agentready setup
demo:           ## roteiro completo, com pausas
	uv run agentready demo all
demo-%:         ## um bloco: make demo-3
	uv run agentready demo $*
test:
	uv run pytest -q
mcp:            ## servidor MCP (stdio)
	uv run agentready mcp
clean:
	rm -rf data/*.duckdb* traces/
