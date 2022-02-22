from ...language.visitor import Visitor


class ValidationRule(Visitor):
    __slots__ = 'context',

    def __init__(self, context):
        self.context = context
