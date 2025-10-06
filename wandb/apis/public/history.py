"""W&B Public API for Run History.

This module provides classes for efficiently scanning and sampling run
history data.

Note:
    This module is part of the W&B Public API and provides methods
    to access run history data. It handles pagination automatically and offers
    both complete and sampled access to metrics logged during training runs.
"""

from __future__ import annotations

import json

from wandb_gql import gql

from wandb.apis.normalize import normalize_exceptions
from wandb.apis.public import api, runs


class HistoryScan:
    """Iterator for scanning complete run history.

    <!-- lazydoc-ignore-class: internal -->
    """

    QUERY = gql(
        """
        query HistoryPage($entity: String!, $project: String!, $run: String!, $minStep: Int64!, $maxStep: Int64!, $pageSize: Int!) {
            project(name: $project, entityName: $entity) {
                run(name: $run) {
                    history(minStep: $minStep, maxStep: $maxStep, samples: $pageSize)
                }
            }
        }
        """
    )

    def __init__(
        self,
        client: api.RetryingClient,
        run: api.public.runs.Run,
        min_step: int,
        max_step: int,
        page_size: int = 1000,
    ):
        """Initialize a HistoryScan instance.

        Args:
            client: The client instance to use for making API calls to the W&B backend.
            run: The run object whose history is to be scanned.
            min_step: The minimum step to start scanning from.
            max_step: The maximum step to scan up to.
            page_size: Number of history rows to fetch per page.
                Default page_size is 1000.
        """
        self.client = client
        self.run = run
        self.page_size = page_size
        self.min_step = min_step
        self.max_step = max_step
        self.page_offset = min_step  # minStep for next page
        self.scan_offset = 0  # index within current page of rows
        self.rows = []  # current page of rows

    def __iter__(self):
        self.page_offset = self.min_step
        self.scan_offset = 0
        self.rows = []
        return self

    def __next__(self):
        """Return the next row of history data with automatic pagination.

        <!-- lazydoc-ignore: internal -->
        """
        while True:
            if self.scan_offset < len(self.rows):
                row = self.rows[self.scan_offset]
                self.scan_offset += 1
                return row
            if self.page_offset >= self.max_step:
                raise StopIteration()
            self._load_next()

    next = __next__

    @normalize_exceptions
    def _load_next(self):
        max_step = self.page_offset + self.page_size
        if max_step > self.max_step:
            max_step = self.max_step
        variables = {
            "entity": self.run.entity,
            "project": self.run.project,
            "run": self.run.id,
            "minStep": int(self.page_offset),
            "maxStep": int(max_step),
            "pageSize": int(self.page_size),
        }

        res = self.client.execute(self.QUERY, variable_values=variables)
        res = res["project"]["run"]["history"]
        self.rows = [json.loads(row) for row in res]
        self.page_offset += self.page_size
        self.scan_offset = 0


class SampledHistoryScan:
    """Iterator for sampling run history data.

    <!-- lazydoc-ignore-class: internal -->
    """

    QUERY = gql(
        """
        query SampledHistoryPage($entity: String!, $project: String!, $run: String!, $spec: JSONString!) {
            project(name: $project, entityName: $entity) {
                run(name: $run) {
                    sampledHistory(specs: [$spec])
                }
            }
        }
        """
    )

    def __init__(
        self,
        client: api.RetryingClient,
        run: runs.Run,
        keys: list,
        min_step: int,
        max_step: int,
        page_size: int = 1000,
    ):
        """Initialize a SampledHistoryScan instance.

        Args:
            client: The client instance to use for making API calls to the W&B backend.
            run: The run object whose history is to be sampled.
            keys: List of keys to sample from the history.
            min_step: The minimum step to start sampling from.
            max_step: The maximum step to sample up to.
            page_size: Number of sampled history rows to fetch per page.
                Default page_size is 1000.
        """
        self.client = client
        self.run = run
        self.keys = keys
        self.page_size = page_size
        self.min_step = min_step
        self.max_step = max_step
        self.page_offset = min_step  # minStep for next page
        self.scan_offset = 0  # index within current page of rows
        self.rows = []  # current page of rows

    def __iter__(self):
        self.page_offset = self.min_step
        self.scan_offset = 0
        self.rows = []
        return self

    def __next__(self):
        """Return the next row of sampled history data with automatic pagination.

        <!-- lazydoc-ignore: internal -->
        """
        while True:
            if self.scan_offset < len(self.rows):
                row = self.rows[self.scan_offset]
                self.scan_offset += 1
                return row
            if self.page_offset >= self.max_step:
                raise StopIteration()
            self._load_next()

    next = __next__

    @normalize_exceptions
    def _load_next(self):
        max_step = self.page_offset + self.page_size
        if max_step > self.max_step:
            max_step = self.max_step
        variables = {
            "entity": self.run.entity,
            "project": self.run.project,
            "run": self.run.id,
            "spec": json.dumps(
                {
                    "keys": self.keys,
                    "minStep": int(self.page_offset),
                    "maxStep": int(max_step),
                    "samples": int(self.page_size),
                }
            ),
        }

        res = self.client.execute(self.QUERY, variable_values=variables)
        res = res["project"]["run"]["sampledHistory"]
        self.rows = res[0]
        self.page_offset += self.page_size
        self.scan_offset = 0
