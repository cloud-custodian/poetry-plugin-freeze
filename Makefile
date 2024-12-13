

lint:
	black --check src tests
	ruff check src tests

format:
	ruff format src tests

test:
	pytest --cov poetry_plugin_freeze tests
