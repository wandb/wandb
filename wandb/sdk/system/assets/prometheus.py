from typing import List

import requests

from wandb.sdk.system.assets.interfaces import Metric


class Prometheus:
    # Poll a prometheus endpoint, parse the response and return a dict of metrics
    # Implements the same Protocol interface as Asset
    name: str
    metrics: List[Metric]

    def __init__(self, url: str) -> None:
        self.url = url
        self.session = requests.Session()

    def parse_prometheus_metrics_endpoint(self) -> None:
        from prometheus_client.parser import text_string_to_metric_families  # type: ignore

        response = self.session.get(self.url)
        # print(response.text)
        for family in text_string_to_metric_families(response.text):
            print(family.type)
            for sample in family.samples:
                if sample.timestamp is not None:
                    print(sample)
                # print("Name: {0} Labels: {1} Value: {2}".format(*sample))

    def poll(self) -> None:
        # Poll the endpoint once
        self.parse_prometheus_metrics_endpoint()

    def serialize(self) -> dict:
        ...
