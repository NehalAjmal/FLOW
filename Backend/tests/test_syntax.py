# Catches copy-paste accidents (like stray lines) in every backend file,
# including ones the other tests never import, such as sessions/service.py.
import pathlib
import py_compile

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent
FILES = [p for p in BACKEND.rglob("*.py")
         if "venv" not in p.parts and "__pycache__" not in p.parts]


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(BACKEND)))
def test_file_compiles(path):
    py_compile.compile(str(path), doraise=True)
