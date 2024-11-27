install:
    poetry install --with dev
    poetry run pre-commit install

test:
    poetry run pytest

lint:
    poetry run pre-commit run --all-files
