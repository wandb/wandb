# -*- coding: utf-8 -*-
"""
`expand` type question
"""
from __future__ import print_function, unicode_literals

import sys

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding.manager import KeyBindingManager
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.filters import IsDone
from prompt_toolkit.layout.controls import TokenListControl
from prompt_toolkit.layout.containers import ConditionalContainer, HSplit
from prompt_toolkit.layout.dimension import LayoutDimension as D
from prompt_toolkit.token import Token

from .. import PromptParameterException
from ..separator import Separator
from .common import default_style
from .common import if_mousedown


PY3 = sys.version_info[0] >= 3

if PY3:
    basestring = str


# custom control based on TokenListControl

class InquirerControl(TokenListControl):
    def __init__(self, choices, default=None, **kwargs):
        self.pointer_index = 0
        self.answered = False
        self._init_choices(choices, default)
        self._help_active = False  # help is activated via 'h' key
        super(InquirerControl, self).__init__(self._get_choice_tokens,
                                              **kwargs)

    def _init_choices(self, choices, default=None):
        # helper to convert from question format to internal format

        self.choices = []  # list (key, name, value)

        if not default:
            default = 'h'
        for i, c in enumerate(choices):
            if isinstance(c, Separator):
                self.choices.append(c)
            else:
                if isinstance(c, basestring):
                    self.choices.append((key, c, c))
                else:
                    key = c.get('key')
                    name = c.get('name')
                    value = c.get('value', name)
                    if default and default == key:
                        self.pointer_index = i
                        key = key.upper()  # default key is in uppercase
                    self.choices.append((key, name, value))
        # append the help choice
        key = 'h'
        if not default:
            self.pointer_index = len(self.choices)
            key = key.upper()  # default key is in uppercase
        self.choices.append((key, 'Help, list all options', None))

    @property
    def choice_count(self):
        return len(self.choices)

    def _get_choice_tokens(self, cli):
        tokens = []
        T = Token

        def _append(index, line):
            if isinstance(line, Separator):
                tokens.append((T.Separator, '   %s\n' % line))
            else:
                key = line[0]
                line = line[1]
                pointed_at = (index == self.pointer_index)

                @if_mousedown
                def select_item(cli, mouse_event):
                    # bind option with this index to mouse event
                    self.pointer_index = index

                if pointed_at:
                    tokens.append((T.Selected, '  %s) %s' % (key, line),
                                   select_item))
                else:
                    tokens.append((T, '  %s) %s' % (key, line),
                                   select_item))
                tokens.append((T, '\n'))

        if self._help_active:
            # prepare the select choices
            for i, choice in enumerate(self.choices):
                _append(i, choice)
            tokens.append((T, '  Answer: %s' %
                           self.choices[self.pointer_index][0]))
        else:
            tokens.append((T.Pointer, '>> '))
            tokens.append((T, self.choices[self.pointer_index][1]))
        return tokens

    def get_selected_value(self):
        # get value not label
        return self.choices[self.pointer_index][2]


def question(message, **kwargs):
    # TODO extract common parts for list, checkbox, rawlist, expand
    # TODO up, down navigation
    if not 'choices' in kwargs:
        raise PromptParameterException('choices')

    choices = kwargs.pop('choices', None)
    default = kwargs.pop('default', None)

    # TODO style defaults on detail level
    style = kwargs.pop('style', default_style)

    ic = InquirerControl(choices, default)

    def get_prompt_tokens(cli):
        tokens = []
        T = Token

        tokens.append((T.QuestionMark, '?'))
        tokens.append((T.Question, ' %s ' % message))
        if not ic.answered:
            tokens.append((T.Instruction, ' (%s)' % ''.join(
                [k[0] for k in ic.choices if not isinstance(k, Separator)])))
        else:
            tokens.append((T.Answer, ' %s' % ic.get_selected_value()))
        return tokens

    #@Condition
    #def is_help_active(cli):
    #    return ic._help_active

    # assemble layout
    layout = HSplit([
        Window(height=D.exact(1),
               content=TokenListControl(get_prompt_tokens)
        ),
        ConditionalContainer(
            Window(ic),
            #filter=is_help_active & ~IsDone()  # ~ bitwise inverse
            filter=~IsDone()  # ~ bitwise inverse
        )
    ])

    # key bindings
    manager = KeyBindingManager.for_prompt()

    @manager.registry.add_binding(Keys.ControlQ, eager=True)
    @manager.registry.add_binding(Keys.ControlC, eager=True)
    def _(event):
        raise KeyboardInterrupt()

    # add key bindings for choices
    for i, c in enumerate(ic.choices):
        if not isinstance(c, Separator):
            def _reg_binding(i, keys):
                # trick out late evaluation with a "function factory":
                # http://stackoverflow.com/questions/3431676/creating-functions-in-a-loop
                @manager.registry.add_binding(keys, eager=True)
                def select_choice(event):
                    ic.pointer_index = i
            if c[0] not in ['h', 'H']:
                _reg_binding(i, c[0])
                if c[0].isupper():
                    _reg_binding(i, c[0].lower())

    @manager.registry.add_binding('H', eager=True)
    @manager.registry.add_binding('h', eager=True)
    def help_choice(event):
        ic._help_active = True

    @manager.registry.add_binding(Keys.Enter, eager=True)
    def set_answer(event):
        ic.answered = True
        event.cli.set_return_value(ic.get_selected_value())

    return Application(
        layout=layout,
        key_bindings_registry=manager.registry,
        mouse_support=True,
        style=style
    )
