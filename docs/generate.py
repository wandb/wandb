from pydocmd import document
from pydocmd.imp import import_object
from pydocmd import loader
from pydocmd.__main__ import main
from yapf.yapflib.yapf_api import FormatCode
import inspect
import sys
import os
import yaml


def trim(docstring):
    if not docstring:
        return ''
    lines = [x.rstrip() for x in docstring.split('\n')]
    lines[0] = lines[0].lstrip()
    debug = False
    if " DEBUG" in docstring:
        debug = True
        print("LINES", lines)

    indent = None
    for i, line in enumerate(lines):
        if i == 0 or not line:
            continue
        new_line = line.lstrip()
        delta = len(line) - len(new_line)
        if debug:
            print("DELTA", delta)
        if indent is None:
            # So gnarly
            if i > 0 and lines[i-1] != "":
                indent = int(delta / 2)
        if indent and delta > indent:
            new_line = ' ' * (delta - indent) + new_line
        lines[i] = new_line

    return '\n'.join(lines)


loader.trim = trim


class PythonLoader(object):
    """
    Expects absolute identifiers to import with #import_object_with_scope().
    """

    def __init__(self, config):
        self.config = config

    def load_section(self, section):
        """
        Loads the contents of a #Section. The `section.identifier` is the name
        of the object that we need to load.

        # Arguments
          section (Section): The section to load. Fill the `section.title` and
            `section.content` values. Optionally, `section.loader_context` can
            be filled with custom arbitrary data to reference at a later point.
        """

        assert section.identifier is not None
        obj, scope = loader.import_object_with_scope(section.identifier)

        #TODO: this is insane
        prefix = None
        if '.' in section.identifier:
            parts = section.identifier.rsplit('.', 2)
            default_title = ".".join(parts[1:])
            prefix = parts[1]
        else:
            default_title = section.identifier

        name = getattr(obj, '__name__', default_title)
        if prefix and name[0].islower() and prefix not in name:
            section.title = ".".join([str(prefix), name])
        else:
            section.title = name
        section.content = trim(loader.get_docstring(obj))
        section.loader_context = {'obj': obj, 'scope': scope}

        # Add the function signature in a code-block.
        if callable(obj):
            sig = loader.get_function_signature(
                obj, scope if inspect.isclass(scope) else None)
            sig, _ = FormatCode(sig, style_config='google')
            section.content = '```python\n{}\n```\n'.format(
                sig.strip()) + section.content


loader.PythonLoader = PythonLoader


class Section(object):
    """
    This is our monkeypatched version of section to enable links to github.  We could put this in google_parser
    """

    def __init__(self, doc, identifier=None, title=None, depth=1, content=None, header_type='html'):
        self.doc = doc
        self.identifier = identifier
        self.title = title
        self.link = None
        try:
            value = import_object(identifier)
            lineno = inspect.getsourcelines(value)[1]
            if len(self.doc.sections) > 0:
                value = import_object(self.doc.sections[0].identifier)
            filename = inspect.getsourcefile(value).split("/client/")[-1]
            branch = os.popen("git rev-parse --abbrev-ref HEAD").read().strip()
            self.link = "https://github.com/wandb/client/blob/{}/{}#L{}".format(branch, filename, lineno)
        except TypeError as e:
            pass
        self.depth = depth
        self.content = content if content is not None else '*Nothing to see here.*'
        self.header_type = header_type

    def maybe_link(self, title):
        if self.link:
            return "{}\n[source]({})".format(self.title, self.link)
        else:
            return title

    def render(self, stream):
        """
        Render the section into *stream*.
        """

        if self.header_type == 'html':
            print('<h{depth} id="{id}">{title}</h{depth}>\n'
                  .format(depth=self.depth, id=self.identifier, title=self.title),
                  file=stream)
        elif self.header_type == 'markdown':
            print('\n' + ('#' * self.depth),
                  self.maybe_link(self.title), file=stream)
        else:
            raise ValueError('Invalid header type: %s' % self.header_type)
        print(self.content, file=stream)

    @property
    def index(self):
        """
        Returns the #Index that this section is associated with, accessed via
        `section.document`.
        """

        return self.document.index


document.Section = Section
sys.argv = ["generate.py", "generate"]
if __name__ == '__main__':
    main()
    config = yaml.load(open("pydocmd.yml"))
    modules = [("docs/markdown/"+list(doc)[0], list(doc.values())[0]) for doc in config["generate"]]
    with open("markdown/README.md", "w") as f:
        f.write(
            "# W&B Documentation\n\nAll api docs are also available on our [documentation site](https://docs.wandb.com)\n\n")
        for link, mods in modules:
            for mod in mods:
                f.write("- [{}]({})\n".format(mod.replace("+", ""), link))
    print("Generated files in the markdown folder!")
