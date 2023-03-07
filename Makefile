

lint:
	black --check src tests
	ruff src tests

test:
	pytest --cov poetry_plugin_freeze tests
