from pydocmd import document
from pydocmd.imp import import_object
from pydocmd.__main__ import main
import inspect
import sys


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
            filename = inspect.getfile(value).split("/client/")[-1]
            lineno = inspect.getsourcelines(value)[1]
            self.link = "https://github.com/wandb/client/blob/feature/docs/" + \
                filename+"#L"+str(lineno)
        except TypeError as e:
            pass
        self.depth = depth
        self.content = content if content is not None else '*Nothing to see here.*'
        self.header_type = header_type

    def maybe_link(self, title):
        if self.link:
            return "[{}]({})".format(self.title, self.link)
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
    print("Generated files in the markdown folder!")
