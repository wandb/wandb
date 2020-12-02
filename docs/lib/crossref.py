# -*- coding: utf8 -*-
# This is an attempt to make crossref's work with :obj:`MyObject`, currently hardcoded locally

from nr.databind.core import Struct
from nr.interface import implements, override
from pydoc_markdown.interfaces import Processor, Resolver
from typing import Dict, List, Optional
import docspec
import logging
import re

logger = logging.getLogger(__name__)



@implements(Processor)
class CrossrefProcessor(Struct):
    """
  Finds references to other objects in Markdown docstrings and produces links to other
  pages. The links are provided by the current #Renderer via the #Resolver interface.

  > __Note__: This processor is a work in progress, and most of the time it just converts
  > references into inline-code.

  The syntax for cross references is as follows:

  ```
  This is a ref to another class: :obj:`PydocmdProcessor`
  You can rename a ref like #this~PydocmdProcessor
  And you can append to the ref name like this: #PydocmdProcessor#s
  ```

  Renders as

  > This is a ref to another class: :obj:`PydocmdProcessor`
  > You can rename a ref like #this~PydocmdProcessor
  > And you can append to the ref name like this: :obj:`PydocmdProcessor`s

  Example configuration:

  ```yml
  processors:
    - type: crossref
  ```
  """

    @override
    def process(self, modules: List[docspec.Module], resolver: Optional[Resolver]):
        unresolved = {}
        if resolver:
            reverse = docspec.ReverseMap(modules)
            docspec.visit(
                modules,
                lambda x: self._preprocess_refs(x, resolver, reverse, unresolved),
            )

        if unresolved:
            summary = []
            for uid, refs in unresolved.items():
                summary.append("  {}: {}".format(uid, ", ".join(refs)))

            logger.warning(
                "%s cross-reference(s) could not be resolved:\n%s",
                sum(map(len, unresolved.values())),
                "\n".join(summary),
            )

    def _preprocess_refs(
        self,
        node: docspec.ApiObject,
        resolver: Resolver,
        reverse: docspec.ReverseMap,
        unresolved: Dict[str, List[str]],
    ) -> None:
        if not node.docstring:
            return

        def handler(match):
            ref = match.group("ref")
            parens = match.group("parens") or ""
            trailing = (match.group("trailing") or "").lstrip("#")
            # Remove the dot from the ref if its trailing (it is probably just
            # the end of the sentence).
            has_trailing_dot = False
            if trailing and trailing.endswith("."):
                trailing = trailing[:-1]
                has_trailing_dot = True
            elif not parens and ref.endswith("."):
                ref = ref[:-1]
                has_trailing_dot = True
            href = resolver.resolve_ref(node, ref)
            if href:
                result = "[`{}`]({})".format(ref + parens + trailing, href)
            else:
                uid = ".".join(x.name for x in reverse.path(node))
                unresolved.setdefault(uid, []).append(ref)
                result = "`{}`".format(ref + parens)
            # Add back the dot.
            if has_trailing_dot:
                result += "."
            return result

        node.docstring = re.sub(
            r"\B:obj:`(?P<ref>[\w\d\._]+)(?P<parens>\(\))?(?P<trailing>#[\w\d\._]+)?`",
            handler,
            node.docstring,
        )

