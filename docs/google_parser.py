"""We had to copy this from: https://github.com/NiklasRosenstein/pydoc-markdown"""
import re


class Preprocessor:
  """
  This class implements the preprocessor for Google and PEP 257 docstrings.
  https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html
  https://www.python.org/dev/peps/pep-0257/
  """
  _param_res = [
    re.compile(r'^(?P<param>\S+):\s+(?P<desc>.+)$'),
    re.compile(r'^(?P<param>\S+)\s+\((?P<type>[^)]+)\):\s+(?P<desc>.+)$'),
    re.compile(r'^(?P<param>\S+)\s+--\s+(?P<desc>.+)$'),
    re.compile(
      r'^(?P<param>\S+)\s+\{\[(?P<type>\S+)\]\}\s+--\s+(?P<desc>.+)$'),
    re.compile(
      r'^(?P<param>\S+)\s+\{(?P<type>\S+)\}\s+--\s+(?P<desc>.+)$'),
  ]

  _keywords_map = {
    'Args:': 'Arguments',
    'Arguments:': 'Arguments',
    'Attributes:': 'Attributes',
    'Example:': 'Examples',
    'Examples:': 'Examples',
    'Keyword Args:': 'Arguments',
    'Keyword Arguments:': 'Arguments',
    'Methods:': 'Methods',
    'Note:': 'Notes',
    'Notes:': 'Notes',
    'Other Parameters:': 'Arguments',
    'Parameters:': 'Arguments',
    'Return:': 'Returns',
    'Returns:': 'Returns',
    'Raises:': 'Raises',
    'References:': 'References',
    'See Also:': 'See Also',
    'Todo:': 'Todo',
    'Warning:': 'Warnings',
    'Warnings:': 'Warnings',
    'Warns:': 'Warns',
    'Yield:': 'Yields',
    'Yields:': 'Yields',
  }

  def __init__(self, config=None):
    self.config = config

  def get_section_names(self):
    return list(self._keywords_map.keys())

  def preprocess_section(self, section):
    """
    Preprocessors a given section into it's components.
    """
    lines = []
    in_codeblock = False
    keyword = None
    components = {}

    for line in section.content.split('\n'):
      line = line.strip()

      if line.startswith("```"):
        print("Codeblock", lines, in_codeblock)
        in_codeblock = not in_codeblock

      if in_codeblock:
        lines.append(line)
        continue

      if line in self._keywords_map:
        keyword = self._keywords_map[line]
        continue

      if keyword is None:
        lines.append(line)
        continue

      if keyword not in components:
        components[keyword] = []

      for param_re in self._param_res:
        param_match = param_re.match(line)
        if param_match:
          if 'type' in param_match.groupdict():
            components[keyword].append(
              '- `{param}` _{type}_ - {desc}'.format(**param_match.groupdict()))
          else:
            components[keyword].append(
              '- `{param}` - {desc}'.format(**param_match.groupdict()))
          break

      if not param_match:
        components[keyword].append('  {line}'.format(line=line))

    for key in components:
      self._append_section(lines, key, components)

    section.content = '\n'.join(lines)

  @staticmethod
  def _append_section(lines, key, sections):
    section = sections.get(key)
    if not section:
      return

    if lines and lines[-1]:
      lines.append('')

    # add an extra line because of markdown syntax
    lines.extend(['**{}**:'.format(key), ''])
    lines.extend(section)
