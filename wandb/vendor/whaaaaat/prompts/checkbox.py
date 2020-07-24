# -*- coding: utf-8 -*-
"""
`checkbox` type question
"""
from __future__ import print_function, unicode_literals
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
from .common import setup_simple_validator, default_style, if_mousedown


# custom control based on TokenListControl


class InquirerControl(TokenListControl):
    def __init__(self, choices, **kwargs):
        self.pointer_index = 0
        self.selected_options = []  # list of names
        self.answered = False
        self._init_choices(choices)
        super(InquirerControl, self).__init__(self._get_choice_tokens,
                                              **kwargs)

    def _init_choices(self, choices):
        # helper to convert from question format to internal format
        self.choices = []  # list (name, value)
        searching_first_choice = True
        for i, c in enumerate(choices):
            if isinstance(c, Separator):
                self.choices.append(c)
            else:
                name = c['name']
                value = c.get('value', name)
                disabled = c.get('disabled', None)
                if 'checked' in c and c['checked'] and not disabled:
                    self.selected_options.append(c['name'])
                self.choices.append((name, value, disabled))
                if searching_first_choice:
                    self.pointer_index = i  # find the first choice
                    searching_first_choice = False

    @property
    def choice_count(self):
        return len(self.choices)

    def _get_choice_tokens(self, cli):
        tokens = []
        T = Token

        def append(index, line):
            if isinstance(line, Separator):
                tokens.append((T.Separator, '  %s\n' % line))
            else:
                line = line[0]
                selected = (line in self.selected_options)
                pointed_at = (index == self.pointer_index)

                @if_mousedown
                def select_item(cli, mouse_event):
                    # bind option with this index to mouse event
                    if line in self.selected_options:
                        self.selected_options.remove(line)
                    else:
                        self.selected_options.append(line)

                if pointed_at:
                    tokens.append((T.Pointer, ' \u276f', select_item))  # ' >'
                else:
                    tokens.append((T, '  ', select_item))
                # 'o ' - FISHEYE
                if choice[2]:  # disabled
                    tokens.append((T, '- %s (%s)' % (choice[0], choice[2])))
                else:
                    if selected:
                        tokens.append((T.Selected, '\u25cf ', select_item))
                    else:
                        tokens.append((T, '\u25cb ', select_item))
    
                    if pointed_at:
                        tokens.append((Token.SetCursorPosition, ''))
    
                    tokens.append((T, line, select_item))
                tokens.append((T, '\n'))

        # prepare the select choices
        for i, choice in enumerate(self.choices):
            append(i, choice)
        tokens.pop()  # Remove last newline.
        return tokens

    def get_selected_values(self):
        # get values not labels
        return [c[0] for c in self.choices if not isinstance(c, Separator) and
                c[0] in self.selected_options]

    @property
    def line_count(self):
        return len(self.choices)


def question(message, **kwargs):
    # TODO add bottom-bar (Move up and down to reveal more choices)
    # TODO extract common parts for list, checkbox, rawlist, expand
    # TODO validate
    if not 'choices' in kwargs:
        raise PromptParameterException('choices')
    # this does not implement default, use checked...
    if 'default' in kwargs:
        raise ValueError('Checkbox does not implement \'default\' '
                         'use \'checked\':True\' in choice!')

    choices = kwargs.pop('choices', None)
    validator = setup_simple_validator(kwargs)

    # TODO style defaults on detail level
    style = kwargs.pop('style', default_style)

    ic = InquirerControl(choices)

    def get_prompt_tokens(cli):
        tokens = []

        tokens.append((Token.QuestionMark, '?'))
        tokens.append((Token.Question, ' %s ' % message))
        if ic.answered:
            nbr_selected = len(ic.selected_options)
            if nbr_selected == 0:
                tokens.append((Token.Answer, ' done'))
            elif nbr_selected == 1:
                tokens.append((Token.Answer, ' [%s]' % ic.selected_options[0]))
            else:
                tokens.append((Token.Answer,
                               ' done (%d selections)' % nbr_selected))
        else:
            tokens.append((Token.Instruction,
                           ' (<up>, <down> to move, <space> to select, <a> '
                           'to toggle, <i> to invert)'))
        return tokens

    # assemble layout
    layout = HSplit([
        Window(height=D.exact(1),
               content=TokenListControl(get_prompt_tokens, align_center=False)
        ),
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

    @manager.registry.add_binding(' ', eager=True)
    def toggle(event):
        pointed_choice = ic.choices[ic.pointer_index][0]  # name
        if pointed_choice in ic.selected_options:
            ic.selected_options.remove(pointed_choice)
        else:
            ic.selected_options.append(pointed_choice)

    @manager.registry.add_binding('i', eager=True)
    def invert(event):
        inverted_selection = [c[0] for c in ic.choices if
                              not isinstance(c, Separator) and
                              c[0] not in ic.selected_options]
        ic.selected_options = inverted_selection

    @manager.registry.add_binding('a', eager=True)
    def all(event):
        all_selected = True  # all choices have been selected
        for c in ic.choices:
            if not isinstance(c, Separator) and c[0] not in ic.selected_options:
                # add missing ones
                ic.selected_options.append(c[0])
                all_selected = False
        if all_selected:
            ic.selected_options = []

    @manager.registry.add_binding(Keys.Down, eager=True)
    def move_cursor_down(event):
        def _next():
            ic.pointer_index = ((ic.pointer_index + 1) % ic.line_count)
        _next()
        while isinstance(ic.choices[ic.pointer_index], Separator) or \
                ic.choices[ic.pointer_index][2]:
            _next()

    @manager.registry.add_binding(Keys.Up, eager=True)
    def move_cursor_up(event):
        def _prev():
            ic.pointer_index = ((ic.pointer_index - 1) % ic.line_count)
        _prev()
        while isinstance(ic.choices[ic.pointer_index], Separator) or \
                ic.choices[ic.pointer_index][2]:
            _prev()

    @manager.registry.add_binding(Keys.Enter, eager=True)
    def set_answer(event):
        ic.answered = True
        # TODO use validator
        event.cli.set_return_value(ic.get_selected_values())

    return Application(
        layout=layout,
        key_bindings_registry=manager.registry,
        mouse_support=True,
        style=style
    )
