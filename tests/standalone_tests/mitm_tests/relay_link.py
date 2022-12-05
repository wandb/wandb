"""Relay control."""

import os

from typing import Optional

import requests


class RelayLink:
    _disabled: bool
    _relay_link_url: Optional[str]

    def __init__(self) -> None:
        self._disabled = True
        relay_link = os.environ.get("RELAY_LINK")
        if not relay_link:
            return
        self._relay_link_url = f"{relay_link}/_control"
        self._disabled = False
        print("Using relay link:", self._relay_link_url)
        self._session = requests.Session()
        
    def _sendit(self, data) -> None:
        prepared_relayed_request = requests.Request(
            method="POST",
            url=self._relay_link_url,
            json=data,
        ).prepare()
        response = self._session.send(prepared_relayed_request)
        response.raise_for_status()

    def pause(self, service) -> None:
        if self._disabled:
            return
        data = {"service": service, "command": "pause"}
        self._sendit(data)

    def unpause(self, service) -> None:
        if self._disabled:
            return
        data = {"service": service, "command": "unpause"}
        self._sendit(data)

    def delay(self, service, seconds) -> None:
        if self._disabled:
            return
        data = {"service": service, "command": "delay", "time": seconds}
        self._sendit(data)
