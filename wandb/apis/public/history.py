"""W&B Public API for Run History and Logs.

This module provides classes for efficiently scanning and sampling run
history data and log lines.

Note:
    This module is part of the W&B Public API and provides methods
    to access run history data and logs. It handles pagination automatically and offers
    both complete and sampled access to metrics logged during training runs and log lines.
"""

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


class LogsScan:
    """Iterator for scanning complete run logs with pagination.
    
    This class handles paginated retrieval of log lines, allowing access to
    runs with more than 10,000 log entries.
    
    <!-- lazydoc-ignore-class: internal -->
    """
    
    QUERY = gql(
        """
        query RunLogsPaginated($projectName: String!, $entityName: String!, $runName: String!, $first: Int!, $after: String) {
            project(name: $projectName, entityName: $entityName) {
                run(name: $runName) {
                    logLines(first: $first, after: $after) {
                        edges {
                            node {
                                id
                                line
                                level
                                timestamp
                            }
                        }
                        pageInfo {
                            hasNextPage
                            endCursor
                        }
                    }
                }
            }
        }
        """
    )
    
    def __init__(
        self,
        client: api.RetryingClient,
        run: api.public.runs.Run,
        page_size: int = 1000,
    ):
        """Initialize a LogsScan instance.
        
        Args:
            client: The client instance to use for making API calls to the W&B backend.
            run: The run object whose logs are to be scanned.
            page_size: Number of log lines to fetch per page (default 1000).
        """
        self.client = client
        self.run = run
        self.page_size = min(page_size, 10000)  # API has a hard limit
        self.cursor = None
        self.has_next = True
        self.current_page = []
        self.page_index = 0
        
    def __iter__(self):
        """Reset the iterator to start from the beginning."""
        self.cursor = None
        self.has_next = True
        self.current_page = []
        self.page_index = 0
        return self
        
    def __next__(self):
        """Return the next log entry with automatic pagination.
        
        <!-- lazydoc-ignore: internal -->
        """
        # If we have items in the current page, return the next one
        if self.page_index < len(self.current_page):
            log = self.current_page[self.page_index]
            self.page_index += 1
            return log
            
        # If no more pages, stop iteration
        if not self.has_next:
            raise StopIteration()
            
        # Load the next page
        self._load_next_page()
        
        # If the new page is empty, stop iteration
        if not self.current_page:
            raise StopIteration()
            
        # Return the first item from the new page
        log = self.current_page[0]
        self.page_index = 1
        return log
    
    next = __next__
    
    @normalize_exceptions
    def _load_next_page(self):
        """Load the next page of logs from the API."""
        variables = {
            "entityName": self.run.entity,
            "projectName": self.run.project,
            "runName": self.run.id,
            "first": self.page_size,
            "after": self.cursor,
        }
        
        response = self.client.execute(self.QUERY, variable_values=variables)
        
        # Parse the response
        self.current_page = []
        if (
            response
            and response.get("project")
            and response["project"].get("run")
            and response["project"]["run"].get("logLines")
        ):
            log_data = response["project"]["run"]["logLines"]
            edges = log_data.get("edges", [])
            page_info = log_data.get("pageInfo", {})
            
            # Update pagination state
            self.has_next = page_info.get("hasNextPage", False)
            self.cursor = page_info.get("endCursor")
            
            # Parse log entries
            for edge in edges:
                if edge.get("node"):
                    node = edge["node"]
                    self.current_page.append({
                        "timestamp": node.get("timestamp", ""),
                        "level": node.get("level", ""),
                        "message": node.get("line", "").strip(),
                    })
        
        self.page_index = 0
