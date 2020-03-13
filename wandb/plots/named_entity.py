import wandb
from wandb import util
from wandb.plots.utils import test_missing, test_types, encode_labels

def named_entity(docs):
        """
        Adds support for spaCy's entity visualizer, which highlights named
            entities and their labels in a text.

        Arguments:
         docs (list, Doc, Span): Document(s) to visualize.

        Returns:
         Nothing. To see plots, go to your W&B run page.

        Example:
         wandb.log({'NER': wandb.plots.NER(docs=doc)})
        """
        spacy = util.get_module("spacy", required="part_of_speech requires the spacy library, install with `pip install spacy`")
        en_core_web_md = util.get_module("en_core_web_md", required="part_of_speech requires the en_core_web_md library, install with `python -m spacy download en_core_web_md`")
        nlp = en_core_web_md.load()

        if (test_missing(docs=docs)):
            #and test_types(docs=docs)):
            wandb.termlog('Visualizing named entity recognition.')
            html = spacy.displacy.render(nlp(str(docs)), style='ent', page=True,
                                        minify=True)
            return wandb.Html(html)
