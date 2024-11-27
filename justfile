install:
    poetry install --with dev

test:
    poetry run pytest

lint:
    poetry run pre-commit run --all-files