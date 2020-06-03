import wandb
from wandb import util
from wandb.plots.utils import test_missing, test_types, encode_labels

def part_of_speech(docs):
        """
        Adds support for spaCy's dependency visualizer which shows
            part-of-speech tags and syntactic dependencies.

        Arguments:
         docs (list, Doc, Span): Document(s) to visualize.

        Returns:
         Nothing. To see plots, go to your W&B run page.

        Example:
         wandb.log({'part_of_speech': wandb.plots.POS(docs=doc)})
        """
        spacy = util.get_module("spacy", required="part_of_speech requires the spacy library, install with `pip install spacy`")
        en_core_web_md = util.get_module("en_core_web_md", required="part_of_speech requires the en_core_web_md library, install with `python -m spacy download en_core_web_md`")
        nlp = en_core_web_md.load()

        if (test_missing(docs=docs)):
            #and test_types(docs=docs)):
            wandb.termlog('Visualizing part of speech.')
            options = {"compact": True, "color": "#1a1c1f",
                "font": "Source Sans Pro", "collapse_punct": True,
                "collapse_phrases": True}
            html = spacy.displacy.render(nlp(str(docs)), style='dep',
                                        minify=True, options=options, page=True)
            return wandb.Html(html)
