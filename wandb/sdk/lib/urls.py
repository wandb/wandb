"""Validation for URLs."""

from __future__ import annotations

import re

from wandb._pydantic import IS_PYDANTIC_V2


def validate_url(url: object) -> None:
    """Validate a URL.

    Args:
        url: The URL to validate.

    Raises:
        ValueError: If the URL is invalid.
        TypeError: If given something other than a string.
    """
    if not isinstance(url, str):
        raise TypeError(f"Expected a string, got {type(url)}")

    if IS_PYDANTIC_V2:
        _validate_url_pydantic(url)
    else:
        _validate_url_custom(url)


def _validate_url_pydantic(url: str) -> None:
    """Validate a URL using Pydantic's validator."""
    from pydantic_core import SchemaValidator, core_schema

    SchemaValidator(
        core_schema.url_schema(
            allowed_schemes=["http", "https"],
            strict=True,
        )
    ).validate_python(url)


def _validate_url_custom(url: str) -> None:
    """Validate a URL.

    We will remove this once we can require Pydantic V2.

    Based on the Django URLValidator, but with a few additional checks.

    Copyright (c) Django Software Foundation and individual contributors.
    All rights reserved.

    Redistribution and use in source and binary forms, with or without modification,
    are permitted provided that the following conditions are met:

        1. Redistributions of source code must retain the above copyright notice,
            this list of conditions and the following disclaimer.

        2. Redistributions in binary form must reproduce the above copyright
            notice, this list of conditions and the following disclaimer in the
            documentation and/or other materials provided with the distribution.

        3. Neither the name of Django nor the names of its contributors may be used
            to endorse or promote products derived from this software without
            specific prior written permission.

    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
    ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
    WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
    DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
    ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
    (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
    LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
    ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
    (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
    SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
    """
    from urllib.parse import urlparse, urlsplit

    ul = "\u00a1-\uffff"  # Unicode letters range (must not be a raw string).

    # IP patterns
    ipv4_re = (
        r"(?:0|25[0-5]|2[0-4][0-9]|1[0-9]?[0-9]?|[1-9][0-9]?)"
        r"(?:\.(?:0|25[0-5]|2[0-4][0-9]|1[0-9]?[0-9]?|[1-9][0-9]?)){3}"
    )
    ipv6_re = r"\[[0-9a-f:.]+\]"  # (simple regex, validated later)

    # Host patterns
    hostname_re = (
        r"[a-z" + ul + r"0-9](?:[a-z" + ul + r"0-9-]{0,61}[a-z" + ul + r"0-9])?"
    )
    # Max length for domain name labels is 63 characters per RFC 1034 sec. 3.1
    domain_re = r"(?:\.(?!-)[a-z" + ul + r"0-9-]{1,63}(?<!-))*"
    tld_re = (
        r"\."  # dot
        r"(?!-)"  # can't start with a dash
        r"(?:[a-z" + ul + "-]{2,63}"  # domain label
        r"|xn--[a-z0-9]{1,59})"  # or punycode label
        r"(?<!-)"  # can't end with a dash
        r"\.?"  # may have a trailing dot
    )
    # host_re = "(" + hostname_re + domain_re + tld_re + "|localhost)"
    # todo?: allow hostname to be just a hostname (no tld)?
    host_re = "(" + hostname_re + domain_re + f"({tld_re})?" + "|localhost)"

    regex = re.compile(
        r"^(?:[a-z0-9.+-]*)://"  # scheme is validated separately
        r"(?:[^\s:@/]+(?::[^\s:@/]*)?@)?"  # user:pass authentication
        r"(?:" + ipv4_re + "|" + ipv6_re + "|" + host_re + ")"
        r"(?::[0-9]{1,5})?"  # port
        r"(?:[/?#][^\s]*)?"  # resource path
        r"\Z",
        re.IGNORECASE,
    )
    schemes = {"http", "https"}
    unsafe_chars = frozenset("\t\r\n")

    scheme = url.split("://")[0].lower()
    split_url = urlsplit(url)
    parsed_url = urlparse(url)

    if parsed_url.netloc == "":
        raise ValueError(f"Invalid URL: {url!r}")
    elif unsafe_chars.intersection(url):
        raise ValueError("URL cannot contain unsafe characters")
    elif scheme not in schemes:
        raise ValueError("URL must start with `http(s)://`")
    elif not regex.search(url):
        raise ValueError(f"{url!r} is not a valid server address")
    elif split_url.hostname is None or len(split_url.hostname) > 253:
        raise ValueError("hostname is invalid")
