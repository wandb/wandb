"""
MIT License

Copyright (c) 2018 Ossian O'Reilly

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
"""
This module provides parsers for parsing different docstring formats.  The
parsers work on docstring data objects that are constructed using the `extract`
module. After parsing, the data of docstring is stored in a dictionary. This
data can for instance be serialized using JSON, or rendered to markdown.
"""
import re
import warnings


class DocString(object):
    """
    This is the base class for parsing docstrings.

    Default behavior of the parser can be modified by passing a dict called
    `config` during initialization. This dict does only have to contain the
    key-value pairs for the configuration settings to change. Possible options
    are listed and explained below.

    Attributes:
        delimiter: A string that is used to identify a section and is placed
            after the section name (e.g., `Arguments:`). Defaults to `': '`.
        arg_delimiter: A string that specifies how to separate arguments in a
            argument list. Defaults to `':'`.
        indent: An int that specifies the minimum number of spaces to use for
            indentation. Defaults to `4`.
        code: Convert code blocks to Markdown. Defaults to `'python'`. Use
            `None` to disable. Use `''` (empty string) to convert code blocks to
            markdown, but disable syntax highlighting.
        ignore_args_for_undefined_headers: A flag that if set to `True` treats
            argument lists as text if the header is unknown, or does not exist. 
        check_args: A flag that if set to `True` checks if all arguments are
            documented in a docstring, and if their types are correct. For this
            option to work, the optional input `args` must be passed upon
            initialization.
        override_annotations: A flag that if set to `True` sets the argument
            annotation field in a docstring (optional) to the value specified by
            the optional input `args`. 
        warn_if_no_arg_doc: Issue a warning if an argument does not have any
            documentation. For this option to work, `args` must be passed.
            Defaults to `True`.
        exclude_warn_if_no_arg_doc: Do no issue warnings for args missing
            documentation if they are part of this list. Defaults to `['self']`.

    """

    def __init__(self, docstring, signature=None, config=None):
        """

        Initialize a new parser.

        Args:
            signature(dict, optional): A dict containing arguments and return
                annotations. See the function `parse_signature' to construct
                this dict from a PEP484 annotated signature. When this argument
                is specified, the parser will assign types to arguments using
                this dict instead of obtaining them from the docstrings.
            config(dict, optional): A dict containing optional configuration
                settings that modify default behavior.

        """
        self.header = {}
        self.docstring = docstring
        self.data = []
        self.signature = signature

        default_config = {}
        default_config['delimiter'] = ':'
        default_config['arg_delimiter'] = ': '
        default_config['indent'] = 4
        default_config['check_args'] = True
        default_config['override_annotations'] = True
        default_config['warn_if_no_arg_doc'] = True
        default_config['exclude_warn_if_no_arg_doc'] = ['self']
        default_config['code'] = 'python'
        default_config['warn_if_undefined_header'] = True
        default_config['ignore_args_for_undefined_headers'] = True

        default_config['headers'] = ''
        default_config['extra_headers'] = ''
        default_config['args'] = ''
        default_config['returns'] = ''

        self._config = get_config(default_config, config)

        # Internals for parsing
        # _section : This variable will hold the contents of each unparsed section
        # _sections : A list that will hold all unparsed sections.
        # _linenum : line number relative to the current section being
        # parsed.
        # _re .. : Regex functions.
        # _indent : This variable will hold the current indentation (number of spaces).

        self._parsing = {
            'indent': 0,
            'linenum': 0,
            'sections': [],
            'section': []
        }
        self._re = {}

    def parse(self, mark_code_blocks=False):
        """
        This method should be overloaded and perform the parsing of all
        sections.

        Args:
            mark_code_blocks: Format code blocks using markdown. Defaults to
                `False`.
        """
        self.data = []
        self.extract_sections()
        for section in self._parsing['sections']:
            self.data.append(self.parse_section(section))

        for i, di in enumerate(self.data):
            self.check_args(di)
            if self.signature:
                self.override_annotations(self.data[i], self.signature['args'],
                                          self._config['args'].split('|'))
                self.override_annotations(
                    self.data[i], {'': self.signature['return_annotation']},
                    self._config['returns'].split('|'))
            if mark_code_blocks:
                self.mark_code_blocks(self.data[i])

        return self.data

    def extract_sections(self):
        """
        This method should be overloaded to specify how to extract sections.
        """
        pass

    def parse_section(self, section):
        """
        This method should be overloaded to specify how to parse a section.
        """
        pass

    def __json__(self):
        """
        Output docstring as JSON data.
        """
        import json

        data = self.data
        data.append(self.header)
        return json.dumps(
            self.data, sort_keys=True, indent=4, separators=(',', ': '))

    def __str__(self):
        """
        This method should be overloaded to specify how to output to plain-text.
        """
        return self.docstring

    def markdown(self):
        """
        Output data relevant data needed for markdown rendering.

        Args:
            filename (str, optional) : select template to use for markdown
                rendering.
        """
        data = self.data
        headers = self._config['headers'].split('|')
        return headers, data

    def check_args(self, section):
        """
        Check if all args have been documented in the docstring and if, they
        have annotations, annotations matches the ones in the function
        signature. This method only works when `signature` have been specified. 

        """
        if not self.signature or not self._config['check_args']:
            return

        docstring_args = {}

        if section['header'] in self._config['args'].split('|'):
            for arg in section['args']:
                docstring_args[arg['field']] = arg

            for arg in self.signature['args']:
                # Skip checks if signature does not contain any annotations
                # or if the argument should not have documentation.
                if not self.signature['args'][arg] or                          \
                   arg in self._config['exclude_warn_if_no_arg_doc']:
                    continue
                if arg not in docstring_args and                               \
                        self._config['warn_if_no_arg_doc']:
                    warnings.warn(
                        'Missing documentation for `%s` in docstring.' % arg,
                        UserWarning)
                elif docstring_args[arg]['signature'] != \
                     '(%s)'%self.signature['args'][arg] and    \
                     docstring_args[arg]['signature'] != '':
                    warnings.warn(
                        'Annotation mismatch for `%s` in docstring.' % arg,
                        UserWarning)
            for arg in docstring_args:
                if arg not in self.signature['args']:
                    warnings.warn(' Found argument `%s` in docstring that does'\
                    ' not exist in function signature.' % arg, UserWarning)

    def override_annotations(self, section, parsed_args, headers):
        """

        Override argument annotations in docstrings with annotations found in
        `args`. 

        """
        if not parsed_args or not self._config['override_annotations']:
            return

        if not section['header'] in headers:
            return

        args = section['args']
        section['args'] = []
        for arg in args:
            out = arg
            if arg['field'] in parsed_args and parsed_args[arg['field']]:
                out['signature'] = parsed_args[arg['field']]
            section['args'].append(out)

    def mark_code_blocks(self, section):
        """

        Enclose code blocks in formatting tags if option `config['code']` is
        not None.

        """
        if not self._config['code']:
            return

        section['text'] = mark_code_blocks(
            section['text'], lang=self._config['code'])


class GoogleDocString(DocString):
    """
    This is the base class for parsing docstrings that are formatted according
    to the Google style guide.

    Google docstrings are treated as sections that begin with a header (say,
    Args) and are then followed by either an argument list or some text.

    The headers are identified based on a keyword search. 

    In addition to the configuration settings provided by the baseclass, the
    GoogleDocString class introduces some additional configurable parameters,
    listed and explained below.

    Attributes:
        headers: A string of header keywords, each separated by `|`. 
        extra_headers: Modify this argument to include additional header
            keywords.
        args: A string that specifies the name of the `Args` section. This value
            is used to assign types to the argument list by passing the argument
            `args` upon initialization (see baseclass for further details).
        returns: A string that specifies the name of the `Returns` section. The
            use of this argument is the same as for `args`.
        

    """

    def __init__(self, docstring, signature=None, config=None):
        """
        Initialize GoogleDocString parser.

        """
        import os

        default_config = {}
        default_config['headers'] = \
         ('Args|Arguments|Returns|Yields|Raises|Note|' +
          'Notes|Example|Examples|Attributes|Todo')
        default_config['extra_headers'] = ''
        default_config['args'] = 'Args|Arguments'
        default_config['returns'] = 'Returns|'

        config = get_config(default_config, config, warn=0)

        if config['extra_headers']:
            config['headers'] += '|' + config['extra_headers']

        super(GoogleDocString, self).__init__(docstring, signature, config)

        self._re = {
            'header': self._compile_header(),
            'indent': self._compile_indent(),
            'arg': self._compile_arg()
        }

    def parse_section(self, section):
        """
        Parses blocks in a section by searching for an argument list, and
        regular notes. The argument list must be the first block in the section.
        A section is broken up into multiple blocks by having empty lines.

        Returns:
            A dictionary that contains the key `args` for holding the argument
            list (`None`) if not found and the key `text` for holding regular
            notes.

        Example:
            ```
            Section:
                This is block 1 and may or not contain an argument list (see
                `args` for details).

                This is block 2 and any should not contain any argument list.
            ```

        """

        # Get header
        lines = section.split('\n')
        header = self._compile_header().findall(lines[0])

        # Skip the first line if it is a header
        header = self._get_header(lines[0])
        self._parsing['linenum'] = int(bool(header))
        text = []

        args = []
        while self._parsing['linenum'] < len(lines):

            arg_data = self._parse_arglist(lines)
            if not header and arg_data and                                    \
            self._config['warn_if_undefined_header']:
                warnings.warn("Undefined header: '%s'" %header                 \
                              + ' followed by an argument list.')
            if (arg_data and header) or                                        \
               (arg_data and not header and not                                \
               self._config['ignore_args_for_undefined_headers']):
                args.append(arg_data)
            else:
                text.append(lines[self._parsing['linenum']])
            self._parsing['linenum'] += 1

        out = {}
        out['header'] = header
        out['text'] = '\n'.join(text)
        out['args'] = args
        return out

    def extract_sections(self):
        """
        Extracts sections from the docstring. Sections are identified by an
        additional header which is a recognized Keyword such as `Args` or
        `Returns`. All text within  a section is indented and the section ends
        after the indention.
        """

        lines = self.docstring.split('\n')
        new_section = True

        for linenumber, line in enumerate(lines):
            # Compute amount of indentation
            current_indent = self._get_indent(line)

            # Capture indent to be able to remove it from the text and also
            # to determine when a section ends.
            # The indent is reset when a new section begins.
            if new_section and self._is_indent(line):
                self._parsing['indent'] = current_indent
                new_section = False

            if self._is_header(line):
                self._err_if_missing_indent(lines, linenumber)
                self._end_section()
                self._begin_section()
                new_section = True
            # Section ends because of a change in indent that is not caused
            # by a line break
            elif line and current_indent < self._parsing['indent']:
                self._end_section()
                self._begin_section()

            self._parsing['section'].append(line[self._parsing['indent']:])

        self._end_section()
        self._begin_section()

    def _parse_arglist(self, lines, require=False):
        arg_data = self._get_arg(lines[self._parsing['linenum']])

        if not arg_data:
            if require:
                raise ValueError('Failed to parse argument list:\n `%s` ' %
                                 (self._parsing['section']))
            return None

        # Take into account that the description can be multi-line
        # the next line has to be indented
        description = [arg_data[0][2]]
        next_line = _get_next_line(lines, self._parsing['linenum'])
        while self._is_indent(next_line):
            self._parsing['linenum'] += 1
            description.append(lines[self._parsing['linenum']])
            next_line = _get_next_line(lines, self._parsing['linenum'])

        return {
            'field': arg_data[0][0],
            'signature': arg_data[0][1],
            'description': '\n'.join(description)
        }

    def _compile_header(self):
        return re.compile(r'^\s*(%s)%s\s*' % (self._config['headers'],
                                              self._config['delimiter']))

    def _compile_indent(self):
        return re.compile(r'(^\s{%s,})' % self._config['indent'])

    def _compile_arg(self):
        return re.compile(
            r'(\w*)\s*(\(.*\))?\s*%s(.*)' % self._config['arg_delimiter'])

    def _err_if_missing_indent(self, lines, linenumber):
        next_line = _get_next_line(lines, linenumber)
        is_next_indent = self._is_indent(next_line)
        if not is_next_indent:
            raise SyntaxError("Missing indent after `%s`" % next_line)

    def _begin_section(self):
        self._parsing['section'] = []
        self._parsing['indent'] = 0

    def _end_section(self):
        section_text = '\n'.join(self._parsing['section'])
        if section_text.strip():
            self._parsing['sections'].append(section_text)

    def _get_indent(self, line):
        """
        Returns the indentation size.
        """
        indent_size = self._re['indent'].findall(line)
        if indent_size:
            return len(indent_size[0])
        else:
            return 0

    def _is_indent(self, line):
        """
        Returns if the line is indented or not.
        """
        indent = self._get_indent(line)
        return bool(indent > 0)

    def _is_header(self, line):
        return bool(self._re['header'].findall(line))

    def _get_header(self, line):
        header = self._re['header'].findall(line)
        if header:
            return header[0]
        else:
            return ''

    def _get_arg(self, line):
        return self._re['arg'].findall(line)

    def _is_arg(self, line):
        return bool(self._re['arg'].findall(line))


def _get_next_line(lines, linenumber):
    """
    Returns the next line but skips over any empty lines.
    An empty line is returned if read past the last line.
    """
    inc = linenumber + 1
    num_lines = len(lines)
    while True:
        if inc == num_lines:
            return ''
        if lines[inc]:
            return lines[inc]
        inc += 1


def parser(obj, choice='Google', args=None, returns=None, config=None):
    """
    Returns a new docstring parser based on selection. Currently, only the
    Google docstring syntax is supported.

    Args:
        obj : A dictionary that contains the docstring and other properties.
            This object is typically obtained by calling the `extract` function.
        choice: Keyword that determines the parser to use. Defaults to
            `'Google'`.


    Returns:
        A parser for the selected docstring syntax.

    Raises:
        NotImplementedError : This exception is raised when no parser is found.

    """
    parsers = {'Google': GoogleDocString}

    if choice in parsers:
        return parsers[choice](obj, args, returns, config)
    else:
        NotImplementedError(
            'The docstring parser `%s` is not implemented' % choice)


def summary(txt):
    """
    Returns the first line of a string.
    """
    lines = txt.split('\n')
    return lines[0]


def parse_signature(args, return_annotation='__return_annotation'):
    """
        Parse the signature e.g., `(int: a, int: b) -> int` and put into a dict 
        {'a' : 'int', 'b' : 'int', '__return_annotation__' : 'int'}

        Args:
            args : string to parse.
            return_annotation(optional) : define key for placing return type in.
                Defaults to `'__return_annotation'`. This default value has been
                chosen to avoid the return type to clash with the arguments.
                


        """

    match = re.findall('\(([\w\W]*?)\)\s*(?:->\s*(\w+))?', args)
    if not match:
        raise ValueError('The string `%s` is not a signature.' % args)
    match = match[0]

    args_out = {'args': {}, 'return_annotation': ''}

    if len(match) > 1:
        args_out['return_annotation'] = match[1]

    # Split the function input string
    counts = {"p": 0, "l": 0, "b": 0, ":": 0}
    marker = 0
    txt = match[0]
    for i, c in enumerate(txt):

        # Count brackets, parentheses and inequality symbols
        if c == "(":  # parentheses
            counts["p"] += 1
        elif c == ")":
            counts["p"] -= 1
        elif c == "<":  # greater than or less than symbols
            counts["l"] += 1
        elif c == ">":
            counts["l"] -= 1
        elif c == "[":  # greater than or less than symbols
            counts["b"] += 1
        elif c == "]":
            counts["b"] -= 1
        elif c == ":":
            counts[":"] += 1

        # Splitting
        if c == ',' and counts["p"] == 0 and counts["l"] == 0 and counts[
                "b"] == 0:
            # PEP 484 annotated string
            if counts[":"]:
                name = txt[marker:i].split(":", 1)[0].strip(' ')
                type_ = txt[marker:i].split(":", 1)[1].strip(' ')
                counts[":"] -= 1
            # No PEP484 string (`:` does not exist)
            else:
                name = txt[marker:i].strip(' ')
                type_ = ''
                if '=' in name:
                    name, type_ = name.split('=')
                    type_ = '=' + type_

            args_out['args'][name] = type_
            marker = i + 1
        elif i == (
                len(txt) - 1
        ) and counts["p"] == 0 and counts["l"] == 0 and counts["b"] == 0:
            # PEP 484 annotated string
            if counts[":"]:
                name = txt[marker:i + 1].split(":", 1)[0].strip(' ')
                type_ = txt[marker:i + 1].split(":", 1)[1].strip(' ')
                counts[":"] -= 1
            # No PEP484 string (`:` does not exist)
            else:
                name = txt[marker:i + 1].strip(' ')
                type_ = ''
                if '=' in name:
                    name, type_ = name.split('=')
                    type_ = '=' + type_

            args_out['args'][name] = type_
            marker = i + 1
    return args_out


def get_config(default, config=None, warn=1):
    """
    Return a dictionary containing default configuration settings and any
    settings that the user has specified. The user settings will override the
    default settings.

    Args:
        default(dict) : A dictionary of default configuration settings.
        config(dict) : A dictionary of user-specified configuration settings. 
        warn: Issue a warning if `config` contains an unknown key (not found in
            `default`).

    Returns:
        dict : User-specified configuration supplemented with default settings
            for field the user has not specified.

    """

    config_out = {}
    # Set defaults
    for key in default:
        config_out[key] = default[key]

    if not config:
        return config_out

    for key in config:
        if key not in default and warn:
            warnings.warn('Unknown option: %s in `config`' % key)
            #assert 0

    # Override defaults
    for key in config:
        config_out[key] = config[key]

    return config_out


def mark_code_blocks(txt, keyword='>>>', split='\n', tag="```", lang='python'):
    """

    Enclose code blocks in formatting tags. Default settings are consistent with
    markdown-styled code blocks for Python code.

    Args:
        txt: String to search for code blocks.
        keyword(optional, string): String that a code block must start with.
        split(optional, string): String that a code block must end with.
        tag(optional, string): String to enclose code block with.
        lang(optional, string) : String that determines what programming
            language is used in all code blocks. Set this to '' to disable
            syntax highlighting in markdown.

    Returns:
        string: A copy of the input with code formatting tags inserted (if any
        code blocks were found).

    """
    import re

    blocks = re.split('^%s' % split, txt, flags=re.M)
    out_blocks = []

    for block in blocks:
        lines = block.split(keyword)
        match = re.findall('(\s*)(%s[\w\W]+)' % keyword,
                           keyword.join(lines[1:]), re.M)
        if match:
            before_code = lines[0]
            indent = match[0][0]
            indented_tag = '%s%s' % (indent, tag)
            code = '%s%s' % (indent, match[0][1])
            out_blocks.append('%s%s%s\n%s%s' % (before_code, indented_tag,
                                                lang, code, indented_tag))
        else:
            out_blocks.append(block)
    return split.join(out_blocks)
