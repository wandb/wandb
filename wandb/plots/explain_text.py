import wandb
from wandb import util
from wandb.plots.utils import test_missing, test_types, encode_labels

def explain_text(text, probas, target_names=None):
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
        eli5 = util.get_module("eli5", required="explain_text requires the eli5 library, install with `pip install eli5`")
        if (test_missing(text=text, probas=probas)):
            #and test_types(proba=proba)):
            wandb.termlog('Visualizing TextExplainer.')
            te = eli5.lime.TextExplainer(random_state=42)
            te.fit(text, probas)
            html = te.show_prediction(target_names=target_names)
            return wandb.Html(html.data)
