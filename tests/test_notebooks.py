import sys
import platform
import pytest


pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 5) or platform.system() == "Windows",
    reason="Our notebook fixture only works in py3, windows was flaking",
)


def test_one_cell(notebook):
    with notebook("one_cell.ipynb") as nb:
        nb.execute_cell(cell_index=1)
        text = nb.cell_output_text(1)
        print(text)
        assert "lovely-dawn-32" in text
        # assert "Failed to query for notebook name" not in text


def test_magic(notebook):
    with notebook("magic.ipynb") as nb:
        nb.execute_cell(cell_index=[1, 2])
        output = nb.cell_output(2)
        print(output)
        assert notebook.base_url in output[0]["data"]["text/html"]
