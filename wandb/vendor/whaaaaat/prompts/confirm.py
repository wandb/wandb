# -*- coding: utf-8 -*-
"""
confirm type question
"""
from __future__ import print_function, unicode_literals
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding.manager import KeyBindingManager
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import Window, HSplit
from prompt_toolkit.layout.controls import TokenListControl
from prompt_toolkit.layout.dimension import LayoutDimension as D
from prompt_toolkit.token import Token
from prompt_toolkit.styles import style_from_dict


# custom control based on TokenListControl


def question(message, **kwargs):
    # TODO need ENTER confirmation
    default = kwargs.pop('default', True)

    # TODO style defaults on detail level
    style = kwargs.pop('style', style_from_dict({
        Token.QuestionMark: '#5F819D',
        #Token.Selected: '#FF9D00',  # AWS orange
        Token.Instruction: '',  # default
        Token.Answer: '#FF9D00 bold',  # AWS orange
        Token.Question: 'bold',
    }))
    status = {'answer': None}

    def get_prompt_tokens(cli):
        tokens = []

        tokens.append((Token.QuestionMark, '?'))
        tokens.append((Token.Question, ' %s ' % message))
        if isinstance(status['answer'], bool):
            tokens.append((Token.Answer, ' Yes' if status['answer'] else ' No'))
        else:
            if default:
                instruction = ' (Y/n)'
            else:
                instruction = ' (y/N)'
            tokens.append((Token.Instruction, instruction))
        return tokens

    # assemble layout
    # TODO this does not work without the HSplit??
    layout = HSplit([
        Window(
            height=D.exact(1),
            content=TokenListControl(get_prompt_tokens, align_center=False),
        )
    ])

    # key bindings
    manager = KeyBindingManager.for_prompt()

    @manager.registry.add_binding(Keys.ControlQ, eager=True)
    @manager.registry.add_binding(Keys.ControlC, eager=True)
    def _(event):
        raise KeyboardInterrupt()

    @manager.registry.add_binding('n')
    @manager.registry.add_binding('N')
    def key_n(event):
        status['answer'] = False
        event.cli.set_return_value(False)

    @manager.registry.add_binding('y')
    @manager.registry.add_binding('Y')
    def key_y(event):
        status['answer'] = True
        event.cli.set_return_value(True)

    @manager.registry.add_binding(Keys.Enter, eager=True)
    def set_answer(event):
        status['answer'] = default
        event.cli.set_return_value(default)

    return Application(
        layout=layout,
        key_bindings_registry=manager.registry,
        mouse_support=False,
        style=style,
        erase_when_done=False,
    )
