# -*- coding: utf-8 -*-
"""
provide colorized output
"""
from __future__ import print_function, unicode_literals
import sys
from prompt_toolkit.shortcuts import print_tokens, style_from_dict, Token


def _print_token_factory(col):
    """Internal helper to provide color names."""
    def _helper(msg):
        style = style_from_dict({
            Token.Color: col,
        })
        tokens = [
            (Token.Color, msg)
        ]
        print_tokens(tokens, style=style)

    def _helper_no_terminal(msg):
        # workaround if we have no terminal
        print(msg)
    if sys.stdout.isatty():
        return _helper
    else:
        return _helper_no_terminal

# used this for color source:
# http://unix.stackexchange.com/questions/105568/how-can-i-list-the-available-color-names
yellow = _print_token_factory('#dfaf00')
blue = _print_token_factory('#0087ff')
gray = _print_token_factory('#6c6c6c')

# TODO
#black
#red
#green
#magenta
#cyan
#white
