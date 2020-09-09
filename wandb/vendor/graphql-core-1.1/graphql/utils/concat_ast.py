import itertools

from ..language.ast import Document


def concat_ast(asts):
    return Document(definitions=list(itertools.chain.from_iterable(
        document.definitions for document in asts
    )))
