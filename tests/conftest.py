from pathlib import Path

import pytest
import shutil


@pytest.fixture
def fixture_root() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_copy(tmp_path):
    def copy(path):
        shutil.copytree(path, tmp_path / path.name)
        return tmp_path / path.name

    return copy
