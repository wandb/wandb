__all__ = [
    "CheckedList",
    "OrderedList",
    "UnorderedList",
    "H1",
    "H2",
    "H3",
    "P",
    "BlockQuote",
    "CalloutBlock",
    "CodeBlock",
    "MarkdownBlock",
    "LaTeXInline",
    "LaTeXBlock",
    "Gallery",
    "Image",
    "WeaveBlock",
    "HorizontalRule",
    "TableOfContents",
    "SoundCloud",
    "Twitter",
    "Spotify",
    "Video",
    "PanelGrid",
]

from abc import ABC, abstractmethod
from dataclasses import dataclass
import re
from typing import Union
import urllib.parse

from wandb.apis.public import PanelGrid
from wandb.sdk.wandb_require_helpers import RequiresReportEditingMixin


class Dispatcher(ABC):
    @classmethod
    @abstractmethod
    def from_json(cls, spec):
        pass


@dataclass
class Block(Dispatcher, RequiresReportEditingMixin):
    @property
    @abstractmethod
    def spec(self):
        pass


class List(Dispatcher):
    @classmethod
    def from_json(cls, spec):
        items = [
            item["children"][0]["children"][0]["text"] for item in spec["children"]
        ]
        checked = [item.get("checked") for item in spec["children"]]
        ordered = spec.get("ordered")

        # NAND: Either checked or ordered or neither (unordered), never both
        if all(x is None for x in checked):
            checked = None
        if checked is not None and ordered is not None:
            raise ValueError(
                "Lists can be checked, ordered or neither (unordered), but not both!"
            )

        if checked:
            return CheckedList(items, checked)
        elif ordered:
            return OrderedList(items)
        else:
            return UnorderedList(items)


class Heading(Dispatcher):
    @classmethod
    def from_json(cls, spec):
        level = spec["level"]
        text = spec["children"][0]["text"]

        level_mapping = {1: H1, 2: H2, 3: H3}

        if level not in level_mapping:
            raise ValueError(f"`level` must be one of {list(level_mapping.keys())}")

        return level_mapping[level](text)


@dataclass
class CheckedList(Block, List):
    items: list
    checked: list

    @property
    def spec(self):
        return {
            "type": "list",
            "children": [
                {
                    "type": "list-item",
                    "children": [{"type": "paragraph", "children": [{"text": item}]}],
                    "checked": check,
                }
                for item, check in zip(self.items, self.checked)
            ],
        }


@dataclass
class OrderedList(Block, List):
    items: list

    @property
    def spec(self):
        return {
            "type": "list",
            "ordered": True,
            "children": [
                {
                    "type": "list-item",
                    "children": [{"type": "paragraph", "children": [{"text": item}]}],
                    "ordered": True,
                }
                for item in self.items
            ],
        }


@dataclass
class UnorderedList(Block, List):
    items: list

    @property
    def spec(self):
        return {
            "type": "list",
            "children": [
                {
                    "type": "list-item",
                    "children": [{"type": "paragraph", "children": [{"text": item}]}],
                }
                for item in self.items
            ],
        }


@dataclass
class H1(Block, List):
    text: str

    @property
    def spec(self):
        return {
            "type": "heading",
            "children": [{"text": self.text}],
            "level": 1,
        }


@dataclass
class H2(Block, List):
    text: str

    @property
    def spec(self):
        return {
            "type": "heading",
            "children": [{"text": self.text}],
            "level": 2,
        }


@dataclass
class H3(Block, List):
    text: str

    @property
    def spec(self):
        return {
            "type": "heading",
            "children": [{"text": self.text}],
            "level": 3,
        }


@dataclass
class P(Block):
    text: str

    @classmethod
    def from_json(cls, spec):
        # Edge case: Inline LaTeX, not Paragraph
        if len(spec["children"]) == 3 and spec["children"][1]["type"] == "latex":
            return LaTeXInline.from_json(spec)

        text = spec["children"][0]["text"]
        return cls(text)

    @property
    def spec(self):
        return {
            "type": "paragraph",
            "children": [{"text": self.text}],
        }


@dataclass
class BlockQuote(Block):
    text: str

    @classmethod
    def from_json(cls, spec):
        text = spec["children"][0]["text"]
        return cls(text)

    @property
    def spec(self):
        return {"type": "block-quote", "children": [{"text": self.text}]}


@dataclass
class CalloutBlock(Block):
    text: Union[str, list]

    def __post_init__(self):
        if isinstance(self.text, str):
            self.text = self.text.split("\n")

    @classmethod
    def from_json(cls, spec):
        text = [child["children"][0]["text"] for child in spec["children"]]
        return cls(text)

    @property
    def spec(self):

        return {
            "type": "callout-block",
            "children": [
                {"type": "callout-line", "children": [{"text": text}]}
                for text in self.text
            ],
        }


@dataclass
class CodeBlock(Block):
    code: Union[str, list]
    language: str = "python"

    def __post_init__(self):
        if isinstance(self.code, str):
            self.code = self.code.split("\n")

    @classmethod
    def from_json(cls, spec):
        code = [child["children"][0]["text"] for child in spec["children"]]
        language = spec.get("language", "python")
        return cls(code, language)

    @property
    def spec(self):
        language = self.language.lower()
        return {
            "type": "code-block",
            "children": [
                {
                    "type": "code-line",
                    "children": [{"text": text}],
                    "language": language,
                }
                for text in self.code
            ],
            "language": language,
        }


@dataclass
class MarkdownBlock(Block):
    text: Union[str, list]

    def __post_init__(self):
        if isinstance(self.text, list):
            self.text = "\n".join(self.text)

    @classmethod
    def from_json(cls, spec):
        text = spec["content"]
        return cls(text)

    @property
    def spec(self):
        return {
            "type": "markdown-block",
            "children": [{"text": ""}],
            "content": self.text,
        }


@dataclass
class LaTeXInline(Block):
    before: Union[str, list]
    latex: Union[str, list]
    after: Union[str, list]

    def __post_init__(self):
        if isinstance(self.before, list):
            self.before = "\n".join(self.before)
        if isinstance(self.latex, list):
            self.latex = "\n".join(self.latex)
        if isinstance(self.after, list):
            self.after = "\n".join(self.after)

    @classmethod
    def from_json(cls, spec):
        before = spec["children"][0]["text"]
        latex = spec["children"][1]["content"]
        after = spec["children"][2]["text"]
        return cls(before, latex, after)

    @property
    def spec(self):
        return {
            "type": "paragraph",
            "children": [
                {"text": self.before},
                {"type": "latex", "children": [{"text": ""}], "content": self.latex},
                {"text": self.after},
            ],
        }


@dataclass
class LaTeXBlock(Block):
    text: Union[str, list]

    def __post_init__(self):
        if isinstance(self.text, list):
            self.text = "\n".join(self.text)

    @classmethod
    def from_json(cls, spec):
        text = spec["content"]
        return cls(text)

    @property
    def spec(self):
        return {
            "type": "latex",
            "children": [{"text": ""}],
            "content": self.text,
            "block": True,
        }


@dataclass
class Gallery(Block):
    ids: list

    @classmethod
    def from_json(cls, spec):
        ids = spec["ids"]
        return cls(ids)

    @classmethod
    def from_report_urls(cls, urls):
        ids = [url.split("--")[-1] for url in urls]
        return cls(ids)

    @property
    def spec(self):
        return {"type": "gallery", "children": [{"text": ""}], "ids": self.ids}


@dataclass
class Image(Block):
    url: str
    caption: str = None

    @classmethod
    def from_json(cls, spec):
        url = spec["url"]
        caption = spec["children"][0]["text"] if spec.get("hasCaption") else None
        return cls(url, caption)

    @property
    def spec(self):
        if self.caption:
            return {
                "type": "image",
                "children": [{"text": self.caption}],
                "url": self.url,
                "hasCaption": True,
            }
        else:
            return {"type": "image", "children": [{"text": ""}], "url": self.url}


@dataclass
class WeaveBlock(Block):
    _spec: dict

    @classmethod
    def from_json(cls, spec):
        return cls(spec)

    @property
    def spec(self):
        return self._spec


@dataclass
class HorizontalRule(Block):
    @classmethod
    def from_json(cls, spec):
        return cls()

    @property
    def spec(self):
        return {"type": "horizontal-rule", "children": [{"text": ""}]}


@dataclass
class TableOfContents(Block):
    @classmethod
    def from_json(cls, spec):
        return cls()

    @property
    def spec(self):
        return {"type": "table-of-contents", "children": [{"text": ""}]}


@dataclass
class SoundCloud(Block):
    url: str

    @classmethod
    def from_json(cls, spec):
        quoted_url = spec["html"].split("url=")[-1].split("&show_artwork")[0]
        url = urllib.parse.unquote(quoted_url)
        return cls(url)

    @property
    def spec(self):
        quoted_url = urllib.parse.quote(self.url)
        return {
            "type": "soundcloud",
            "html": f'<iframe width="100%" height="400" scrolling="no" frameborder="no" src="https://w.soundcloud.com/player/?visual=true&url={quoted_url}&show_artwork=true"></iframe>',
            "children": [{"text": ""}],
        }


@dataclass
class Twitter(Block):
    embed_html: str

    def __post_init__(self):
        # remove script tag
        pattern = r" <script[\s\S]+?/script>"
        self.embed_html = re.sub(pattern, "\n", self.embed_html)

    @classmethod
    def from_json(cls, spec):
        embed_html = spec["html"]
        return cls(embed_html)

    @property
    def spec(self):
        return {"type": "twitter", "html": self.embed_html, "children": [{"text": ""}]}


@dataclass
class Spotify(Block):
    spotify_id: str

    @classmethod
    def from_json(cls, spec):
        return cls(spec["spotifyID"])

    @classmethod
    def from_url(cls, url):
        spotify_id = url.split("/")[-1].split("?")[0]
        return cls(spotify_id)

    @property
    def spec(self):
        return {
            "type": "spotify",
            "spotifyType": "track",
            "spotifyID": self.spotify_id,
            "children": [{"text": ""}],
        }


@dataclass
class Video(Block):
    url: str

    @classmethod
    def from_json(cls, spec):
        return cls(spec["url"])

    @property
    def spec(self):
        return {
            "type": "video",
            "url": self.url,
            "children": [{"text": ""}],
        }


block_mapping = {
    "block-quote": BlockQuote,
    "callout-block": CalloutBlock,
    "code-block": CodeBlock,
    "gallery": Gallery,
    "heading": Heading,
    "horizontal-rule": HorizontalRule,
    "image": Image,
    "latex": LaTeXBlock,
    "list": List,
    "markdown-block": MarkdownBlock,
    "panel-grid": PanelGrid,
    "paragraph": P,
    "table-of-contents": TableOfContents,
    "weave-panel": WeaveBlock,
    "video": Video,
    "spotify": Spotify,
    "twitter": Twitter,
    "soundcloud": SoundCloud,
}
