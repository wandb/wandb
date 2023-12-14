from nbclient import NotebookClient
from nbclient.client import CellExecutionError


class WandbNotebookClient(NotebookClient):
    def execute_cells(self, cell_index=0, execution_count=None, store_history=True):
        """Execute a specific cell.  Since we always execute setup.py in the first
        cell we increment the index offset here
        """
        if not isinstance(cell_index, list):
            cell_index = [cell_index]
        executed_cells = []

        for idx in cell_index:
            try:
                cell = self.nb["cells"][idx + 1]
                ecell = super().execute_cell(
                    cell,
                    idx + 1,
                    execution_count=execution_count,
                    store_history=store_history,
                )
            except CellExecutionError as e:
                print("Cell output before exception:")
                print("=============================")
                for output in cell["outputs"]:
                    if output["output_type"] == "stream":
                        print(output["text"])
                raise e
            for output in ecell["outputs"]:
                if output["output_type"] == "error":
                    print("Error in cell: %s" % idx + 1)
                    print("\n".join(output["traceback"]))
                    raise ValueError(output["evalue"])
            executed_cells.append(ecell)

        return executed_cells

    def execute_all(self, store_history=True):
        return self.execute_cells(list(range(len(self.nb["cells"]) - 1)), store_history)

    def cell_output_text(self, cell_index):
        """Return cell text output

        Arguments:
            cell_index {int} -- cell index in notebook

        Returns:
            str -- Text output
        """

        text = ""
        outputs = self.nb["cells"][cell_index + 1]["outputs"]
        for output in outputs:
            if "text" in output:
                text += output["text"]

        return text

    def all_output_text(self):
        text = ""
        for i in range(len(self.nb["cells"]) - 1):
            text += self.cell_output_text(i)
        return text

    @property
    def cells(self):
        return iter(self.nb["cells"][1:])

    def cell_output(self, cell_index):
        """Return a cells outputs

        NOTE: Since we always execute an init cell we adjust the offset by 1

        Arguments:
            cell_index {int} -- cell index in notebook

        Returns:
            list -- List of outputs for the given cell
        """

        outputs = self.nb["cells"][cell_index + 1]["outputs"]
        return outputs
