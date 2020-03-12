import wandb
from wandb import util
import eli5
from eli5.lime import TextExplainer
from eli5 import explain_weights, explain_prediction
from eli5 import format_as_html, format_as_text, format_html_styles
from IPython.display import display, HTML
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
        if (test_missing(text, probas)):
            #and test_types(proba=proba)):
            probas = np.array(probas)

            te = TextExplainer(**kwargs)
            te.fit(doc, probas)
            html = te.show_prediction()
            return wandb.Html(html.data)
