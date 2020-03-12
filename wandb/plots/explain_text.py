import wandb
from wandb import util
from wandb.plots.utils import test_missing, test_types, encode_labels

chart_limit = wandb.Table.MAX_ROWS

def explain_text(text, probas):
        """
        ExplainText adds support for eli5's LIME based TextExplainer.

        Arguments:
         text (str): Text to explain
         probas (black-box classification pipeline): A function which
                        takes a list of strings (documents) and returns a matrix
                        of shape (n_samples, n_classes) with probability values,
                        i.e. a row per document and a column per output label.

        Returns:
         Nothing. To see plots, go to your W&B run page.

        Example:
         wandb.log({'roc': wandb.plots.ExplainText(text, probas)})
        """
        eli5 = util.import_module("eli5")
        if (test_missing(text, probas)):
            #and test_types(proba=proba)):
            probas = np.array(probas)

            te = eli5.lime.TextExplainer(**kwargs)
            te.fit(doc, probas)
            html = te.show_prediction()
            return wandb.Html(html.data)
