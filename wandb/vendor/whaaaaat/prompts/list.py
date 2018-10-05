# -*- coding: utf-8 -*-
"""
`list` type question
"""
from __future__ import print_function
from __future__ import unicode_literals

import sys

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding.manager import KeyBindingManager
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.filters import IsDone
from prompt_toolkit.layout.controls import TokenListControl
from prompt_toolkit.layout.containers import ConditionalContainer, \
    ScrollOffsets, HSplit
from prompt_toolkit.layout.dimension import LayoutDimension as D
from prompt_toolkit.token import Token

from .. import PromptParameterException
from ..separator import Separator
from .common import if_mousedown, default_style

# custom control based on TokenListControl
# docu here:
# https://github.com/jonathanslenders/python-prompt-toolkit/issues/281
# https://github.com/jonathanslenders/python-prompt-toolkit/blob/master/examples/full-screen-layout.py
# https://github.com/jonathanslenders/python-prompt-toolkit/blob/master/docs/pages/full_screen_apps.rst


PY3 = sys.version_info[0] >= 3

if PY3:
    basestring = str


class InquirerControl(TokenListControl):
    def __init__(self, choices, **kwargs):
        self.selected_option_index = 0
        self.answered = False
        self.choices = choices
        self._init_choices(choices)
        super(InquirerControl, self).__init__(self._get_choice_tokens,
                                              **kwargs)

    def _init_choices(self, choices, default=None):
        # helper to convert from question format to internal format
        self.choices = []  # list (name, value, disabled)
        searching_first_choice = True
        for i, c in enumerate(choices):
            if isinstance(c, Separator):
                self.choices.append((c, None, None))
            else:
                if isinstance(c, basestring):
                    self.choices.append((c, c, None))
                else:
                    name = c.get('name')
                    value = c.get('value', name)
                    disabled = c.get('disabled', None)
                    self.choices.append((name, value, disabled))
                if searching_first_choice:
                    self.selected_option_index = i  # found the first choice
                    searching_first_choice = False

    @property
    def choice_count(self):
        return len(self.choices)

    def _get_choice_tokens(self, cli):
        tokens = []
        T = Token

        def append(index, choice):
            selected = (index == self.selected_option_index)

            @if_mousedown
            def select_item(cli, mouse_event):
                # bind option with this index to mouse event
                self.selected_option_index = index
                self.answered = True
                cli.set_return_value(None)

            tokens.append((T.Pointer if selected else T, ' \u276f ' if selected
            else '   '))
            if selected:
                tokens.append((Token.SetCursorPosition, ''))
            if choice[2]:  # disabled
                tokens.append((T.Selected if selected else T,
                               '- %s (%s)' % (choice[0], choice[2])))
            else:
                tokens.append((T.Selected if selected else T, str(choice[0]),
                               select_item))
            tokens.append((T, '\n'))

        # prepare the select choices
        for i, choice in enumerate(self.choices):
            append(i, choice)
        tokens.pop()  # Remove last newline.
        return tokens

    def get_selection(self):
        return self.choices[self.selected_option_index]


def question(message, **kwargs):
    # TODO disabled, dict choices
    if not 'choices' in kwargs:
        raise PromptParameterException('choices')

    choices = kwargs.pop('choices', None)
    default = kwargs.pop('default', 0)  # TODO

    # TODO style defaults on detail level
    style = kwargs.pop('style', default_style)

    ic = InquirerControl(choices)

    def get_prompt_tokens(cli):
        tokens = []

        tokens.append((Token.QuestionMark, '?'))
        tokens.append((Token.Question, ' %s ' % message))
        if ic.answered:
            tokens.append((Token.Answer, ' ' + ic.get_selection()[0]))
        else:
            tokens.append((Token.Instruction, ' (Use arrow keys)'))
        return tokens

    # assemble layout
    layout = HSplit([
        Window(content=TokenListControl(get_prompt_tokens, align_center=False)),
        ConditionalContainer(
            Window(
                ic,
                width=D.exact(43),
                height=D(min=3),
                scroll_offsets=ScrollOffsets(top=1, bottom=1)
            ),
            filter=~IsDone()
        )
    ])

    # key bindings
    manager = KeyBindingManager.for_prompt()

    @manager.registry.add_binding(Keys.ControlQ, eager=True)
    @manager.registry.add_binding(Keys.ControlC, eager=True)
    def _(event):
        raise KeyboardInterrupt()
        # event.cli.set_return_value(None)

    @manager.registry.add_binding(Keys.Down, eager=True)
    def move_cursor_down(event):
        def _next():
            ic.selected_option_index = (
                (ic.selected_option_index + 1) % ic.choice_count)
        _next()
        while isinstance(ic.choices[ic.selected_option_index][0], Separator) or\
                ic.choices[ic.selected_option_index][2]:
            _next()

    @manager.registry.add_binding(Keys.Up, eager=True)
    def move_cursor_up(event):
        def _prev():
            ic.selected_option_index = (
                (ic.selected_option_index - 1) % ic.choice_count)
        _prev()
        while isinstance(ic.choices[ic.selected_option_index][0], Separator) or \
                ic.choices[ic.selected_option_index][2]:
            _prev()

    @manager.registry.add_binding(Keys.Enter, eager=True)
    def set_answer(event):
        ic.answered = True
        event.cli.set_return_value(ic.get_selection()[1])

    return Application(
        layout=layout,
        key_bindings_registry=manager.registry,
        mouse_support=True,
        style=style
    )
