import wandb
from wandb import util
from wandb.plots.utils import test_missing, test_types, encode_labels
chart_limit = wandb.Table.MAX_ROWS

def roc(y_true=None, y_probas=None, labels=None,
        plot_micro=True, plot_macro=True, classes_to_plot=None):
        """
        Calculates receiver operating characteristic scores and visualizes them as the
         ROC curve.

        Arguments:
         y_true (arr): Test set labels.
         y_probas (arr): Test set predicted probabilities.
         labels (list): Named labels for target varible (y). Makes plots easier to
                         read by replacing target values with corresponding index.
                         For example labels= ['dog', 'cat', 'owl'] all 0s are
                         replaced by 'dog', 1s by 'cat'.

        Returns:
         Nothing. To see plots, go to your W&B run page then expand the 'media' tab
               under 'auto visualizations'.

        Example:
         wandb.log({'roc': wandb.plots.ROC(y_true, y_probas, labels)})
        """
        np = util.get_module("numpy", required="roc requires the numpy library, install with `pip install numpy`")
        sklearn = util.get_module("sklearn", required="roc requires the scikit library, install with `pip install scikit-learn`")
        from sklearn.metrics import roc_curve, auc

        if (test_missing(y_true=y_true, y_probas=y_probas) and
            test_types(y_true=y_true, y_probas=y_probas)):
            y_true = np.array(y_true)
            y_probas = np.array(y_probas)
            classes = np.unique(y_true)
            probas = y_probas

            if classes_to_plot is None:
                classes_to_plot = classes

            fpr_dict = dict()
            tpr_dict = dict()

            indices_to_plot = np.in1d(classes, classes_to_plot)
            def roc_table(fpr_dict, tpr_dict, classes, indices_to_plot):
                data=[]
                count = 0

                for i, to_plot in enumerate(indices_to_plot):
                    fpr_dict[i], tpr_dict[i], _ = roc_curve(y_true, probas[:, i],
                                                            pos_label=classes[i])
                    if to_plot:
                        roc_auc = auc(fpr_dict[i], tpr_dict[i])
                        for j in range(len(fpr_dict[i])):
                            if labels is not None and (isinstance(classes[i], int)
                                        or isinstance(classes[0], np.integer)):
                                class_dict = labels[classes[i]]
                            else:
                                class_dict = classes[i]
                            fpr = [class_dict, round(fpr_dict[i][j], 3), round(tpr_dict[i][j], 3)]
                            data.append(fpr)
                            count+=1
                            if count >= chart_limit:
                                wandb.termwarn("wandb uses only the first %d datapoints to create the plots."% wandb.Table.MAX_ROWS)
                                break
                return wandb.visualize(
                    'wandb/roc/v1', wandb.Table(
                    columns=['class', 'fpr', 'tpr'],
                    data=data
                ))
            return roc_table(fpr_dict, tpr_dict, classes, indices_to_plot)
