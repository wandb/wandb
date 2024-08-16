#!/usr/bin/env python

import re

import requests


def get_latest_go_version() -> str:
    """Fetches the latest Go version from the Go website."""
    url = "https://go.dev/VERSION?m=text"
    response = requests.get(url)
    if response.status_code == 200:
        # Parse the version from the response
        match = re.search(r"go(\d+\.\d+\.\d+)", response.text)
        if match:
            return match.group(1)
        raise ValueError(f"Failed to parse the latest Go version: {response.text}")
    else:
        raise ValueError(f"Failed to parse the latest Go version: {response.text}")


if __name__ == "__main__":
    # print the latest Go version
    print(get_latest_go_version())
