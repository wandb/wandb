try:
    from nbclient import NotebookClient
    from nbclient.client import CellExecutionError
except ImportError:  # TODO: no fancy notebook fun in python2
    NotebookClient = object


class WandbNotebookClient(NotebookClient):
    def execute_cell(self, cell_index=0, execution_count=None,
                     store_history=True):
        if not isinstance(cell_index, list):
            cell_index = [cell_index]
        executed_cells = []

        for idx in cell_index:
            try: 
                cell = self.nb['cells'][idx]
                ecell = super().execute_cell(
                    cell,
                    idx,
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
                    raise ValueError(output["evalue"])
            executed_cells.append(ecell)

        return executed_cells

    def cell_output_text(self, cell_index):
        """Return cell text output

        Arguments:
            cell_index {int} -- cell index in notebook

        Returns:
            str -- Text output
        """

        text = ''
        outputs = self.nb['cells'][cell_index]['outputs']
        for output in outputs:
            if 'text' in output:
                text += output['text']

        return text

    def cell_output(self, cell_index):
        """Return cell text output

        Arguments:
            cell_index {int} -- cell index in notebook

        Returns:
            list -- List of outputs for the given cell
        """

        outputs = self.nb['cells'][cell_index]['outputs']
        return outputs
