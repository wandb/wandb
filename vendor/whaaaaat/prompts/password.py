# -*- coding: utf-8 -*-
"""
`password` type question
"""
from __future__ import print_function, unicode_literals

from . import input 

# use std prompt-toolkit control


def question(message, **kwargs):
    kwargs['is_password'] = True
    return input.question(message, **kwargs)
