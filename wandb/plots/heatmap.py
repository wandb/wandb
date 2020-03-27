import wandb
from wandb import util
from wandb.plots.utils import test_missing, test_types, encode_labels
chart_limit = wandb.Table.MAX_ROWS

def heatmap(x_labels, y_labels, matrix_values, show_text=False):
        """
        Generates a heatmap.

        Arguments:
         matrix_values (arr): 2D dataset of shape x_labels * y_labels, containing
                            heatmap values that can be coerced into an ndarray.
         x_labels  (list): Named labels for rows (x_axis).
         y_labels  (list): Named labels for columns (y_axis).
         show_text (bool): Show text values in heatmap cells.

        Returns:
         Nothing. To see plots, go to your W&B run page then expand the 'media' tab
               under 'auto visualizations'.

        Example:
         wandb.log({'heatmap': wandb.plots.HeatMap(x_labels, y_labels,
                    matrix_values)})
        """
        np = util.get_module("numpy", required="roc requires the numpy library, install with `pip install numpy`")
        scikit = util.get_module("sklearn", required="roc requires the scikit library, install with `pip install scikit-learn`")

        if (test_missing(x_labels=x_labels, y_labels=y_labels,
            matrix_values=matrix_values) and test_types(x_labels=x_labels,
            y_labels=y_labels, matrix_values=matrix_values)):
            matrix_values = np.array(matrix_values)
            wandb.termlog('Visualizing heatmap.')

            def heatmap_table(x_labels, y_labels, matrix_values, show_text):
                x_axis=[]
                y_axis=[]
                values=[]
                count = 0
                for i, x in enumerate(x_labels):
                    for j, y in enumerate(y_labels):
                        x_axis.append(x)
                        y_axis.append(y)
                        values.append(matrix_values[j][i])
                        count+=1
                        if count >= chart_limit:
                            wandb.termwarn("wandb uses only the first %d datapoints to create the plots."% wandb.Table.MAX_ROWS)
                            break
                if show_text:
                    heatmap_key = 'wandb/heatmap/v1'
                else:
                    heatmap_key = 'wandb/heatmap_no_text/v1'
                return wandb.visualize(
                    heatmap_key, wandb.Table(
                    columns=['x_axis', 'y_axis', 'values'],
                    data=[
                        [x_axis[i], y_axis[i], round(values[i], 2)] for i in range(len(x_axis))
                    ]
                ))
            return heatmap_table(x_labels, y_labels, matrix_values, show_text)
