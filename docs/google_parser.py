"""We had to copy this from: https://github.com/NiklasRosenstein/pydoc-markdown"""
import re
import os


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
  _obj_re = re.compile(r':obj:\S+')

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

  def resolve_objects(self, line):
    for link in re.findall(self._obj_re, line):
      ref = link.split(":")[-1]
      line = line.replace(link, "[{}](#{})".format(ref, ref.lower().strip("`")))
    return line

  def preprocess_section(self, section):
    """
    Preprocessors a given section into it's components.
    """
    lines = []
    in_codeblock = False
    in_attribute = False
    keyword = None
    components = {}
    debug = section.identifier == os.getenv("IDENTIFIER")  # "wandb.apis.public.Run.scan_history"

    for line in section.content.split('\n'):
      indented = line.startswith("  ")
      line = line.strip()
      if debug:
          print("YO", indented)

      if line.startswith("```"):
        if line == "```" and not in_codeblock:
            line = "```python"
        if debug:
            print("Codeblock %s" % "starting" if not in_codeblock else "closed", line, lines)
        in_codeblock = not in_codeblock

      if in_codeblock:
        if keyword:
          if keyword not in components:
              components[keyword] = []
          components[keyword].append(line)
        else:
          lines.append(line)
        continue
      elif line.startswith("```") and keyword:
        components[keyword].append(line)
        continue

      if line in self._keywords_map:
        keyword = self._keywords_map[line]
        continue

      if keyword is None:
        if indented and not lines[-1].startswith("```"):
            if debug:
                print("Joining new lines", lines[-1], line)
            lines[-1] = lines[-1] + ' ' + line
        else:
            lines.append(line)
        continue

      if keyword not in components:
        components[keyword] = []

      for param_re in self._param_res:
        param_match = param_re.match(line)
        if param_match:
          matches = param_match.groupdict()
          pytype = matches.get("type")
          desc = self.resolve_objects(matches.get("desc"))
          param = matches.get("param")
          if pytype:
            pytype = self.resolve_objects(pytype)
            components[keyword].append('- `{param}` _{type}_ - {desc}'.format(param=param, desc=desc, type=pytype))
          else:
            components[keyword].append('- `{param}` - {desc}'.format(param=param, desc=desc))
          break

      line=self.resolve_objects(line)

      if not param_match:
        if len(components[keyword]) > 0 and not components[keyword][-1].startswith("```"):
            # Add to previous line
            if debug:
                print("Adding to previous", components[keyword][-1], line)
            components[keyword][-1]=components[keyword][-1] + ' ' + line
        else:
            components[keyword].append(' {line}'.format(line=line))

    for key in components:
      self._append_section(lines, key, components)

    if debug:
        print(lines)
    section.content='\n'.join(lines)

  @staticmethod
  def _append_section(lines, key, sections):
    section=sections.get(key)
    if not section:
      return

    if lines and lines[-1]:
      lines.append('')

    # add an extra line because of markdown syntax
    lines.extend(['**{}**:'.format(key), ''])
    lines.extend(section)
