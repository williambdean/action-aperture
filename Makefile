install: 
	uv tool install . --force --no-cache

lint:
	uvx ruff check .

format:
	uvx ruff format .
