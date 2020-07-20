import sys
import pytest


@pytest.mark.skipif(sys.version_info < (3, 5), reason="Our notebook fixture only works in py3")
def test_one_cell(notebook):
    with notebook("one_cell.ipynb") as nb:
        nb.execute_cell(cell_index=1)
        text = nb.cell_output_text(1)
        print(text)
        assert "lovely-dawn-32" in text
        # assert "Failed to query for notebook name" not in text
