# The MIT License (MIT)

# Copyright (c) 2013 Peter M. Elias

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE


def import_module(target, relative_to=None):
    target_parts = target.split('.')
    target_depth = target_parts.count('')
    target_path = target_parts[target_depth:]
    target = target[target_depth:]
    fromlist = [target]
    if target_depth and relative_to:
        relative_parts = relative_to.split('.')
        relative_to = '.'.join(relative_parts[:-(target_depth - 1) or None])
    if len(target_path) > 1:
        relative_to = '.'.join(filter(None, [relative_to]) + target_path[:-1])
        fromlist = target_path[-1:]
        target = fromlist[0]
    elif not relative_to:
        fromlist = []
    mod = __import__(relative_to or target, globals(), locals(), fromlist)
    return getattr(mod, target, mod)
