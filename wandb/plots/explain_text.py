import wandb
from wandb import util
from wandb.plots.utils import test_missing, test_types, encode_labels
eli5 = util.get_module("eli5", required="Explaining texts requires eli5")
np = util.get_module("numpy", required="Logging plots requires numpy")
chart_limit = wandb.Table.MAX_ROWS
import eli5
import eli5.lime.TextExplainer

def roc(y_true=None, y_probas=None):
        """
        ExplainText adds support for eli5's TextExplainer.

        Arguments:
         args (arr): Add args.

        Returns:
         Nothing. To see plots, go to your W&B run page.

        Example:
         wandb.log({'roc': wandb.plots.ExplainText()})
        """
        if (test_missing(model=model) and
            test_types(model=model)):
            probas = np.array(probas)

            te = TextExplainer(**kwargs)
            te.fit(doc, model.predict_proba)
            html = te.show_prediction()
            print(html.data)
            return wandb.Html(html.data)
