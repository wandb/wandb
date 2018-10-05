# -*- coding: utf-8 -*-
"""
`input` type question
"""
from __future__ import print_function, unicode_literals
from prompt_toolkit.token import Token
from prompt_toolkit.shortcuts import create_prompt_application
from prompt_toolkit.validation import Validator, ValidationError
from prompt_toolkit.layout.lexers import SimpleLexer

from .common import default_style

# use std prompt-toolkit control


def question(message, **kwargs):
    default = kwargs.pop('default', '')
    validate_prompt = kwargs.pop('validate', None)
    if validate_prompt:
        if issubclass(validate_prompt, Validator):
            kwargs['validator'] = validate_prompt()
        elif callable(validate_prompt):
            class _InputValidator(Validator):
                def validate(self, document):
                    verdict = validate_prompt(document.text)
                    if not verdict == True:
                        if verdict == False:
                            verdict = 'invalid input'
                        raise ValidationError(
                            message=verdict,
                            cursor_position=len(document.text))
            kwargs['validator'] = _InputValidator()

    # TODO style defaults on detail level
    kwargs['style'] = kwargs.pop('style', default_style)

    def _get_prompt_tokens(cli):
        return [
            (Token.QuestionMark, '?'),
            (Token.Question, ' %s  ' % message)
        ]

    return create_prompt_application(
        get_prompt_tokens=_get_prompt_tokens,
        lexer=SimpleLexer(Token.Answer),
        default=default,
        **kwargs
    )
