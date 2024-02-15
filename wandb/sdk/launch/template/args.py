"""Functions for creating run template parameters for command line arguments."""

import argparse


class CliParser:
    """Wrapper for a command line argument parser that can be used as a run template parameter."""

    def __init__(
        self,
        parser: argparse.ArgumentParser,
    ):
        self.parser = parser

    def get_schema(self):
        """Extract a schema from the parser."""
