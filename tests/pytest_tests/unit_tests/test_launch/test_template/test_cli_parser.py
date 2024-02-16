import argparse

from wandb.sdk.launch import template


def test_extract_schema():
    """Test schema extraction for a simple case with 1 argument and 2 options."""
    parser = argparse.ArgumentParser(description="Test parser")
    parser.add_argument("config", help="config help")
    parser.add_argument("--foo", help="foo help")
    parser.add_argument("--bar", nargs=1, help="bar help")
    schema = template.CliParser(parser).extract_schema()
    assert schema["description"] == "Test parser"
    assert schema["arguments"] == [
        {"name": "config", "type": "string", "help": "config help"}
    ]
    assert schema["options"] == [
        {"name": "--foo", "type": "string", "help": "foo help"},
        {"name": "--bar", "type": "string", "help": "bar help", "nargs": "1"},
    ]


def test_extract_schema_subcommands():
    """Test schema extraction for a parser with subcommands."""
    parser = argparse.ArgumentParser(description="Test parser")
    parser.add_argument("--foo", help="foo help")
    subparsers = parser.add_subparsers()
    subparser1 = subparsers.add_parser("foo")
    subparser1.add_argument("--foo", help="foo help")
    subparser2 = subparsers.add_parser("bar")
    subparser2.add_argument("config", help="config help")
    subparser2.add_argument("--bar", help="bar help")
    schema = template.CliParser(parser).extract_schema()
    assert schema["description"] == "Test parser"
    assert schema["subcommands"] == [
        {
            "name": "foo",
            "description": None,
            "arguments": [],
            "options": [{"name": "--foo", "type": "string", "help": "foo help"}],
            "subcommands": [],
        },
        {
            "name": "bar",
            "description": None,
            "arguments": [{"name": "config", "type": "string", "help": "config help"}],
            "options": [{"name": "--bar", "type": "string", "help": "bar help"}],
            "subcommands": [],
        },
    ]


def test_extract_schema_nested_subcommands():
    """Test schema extraction for a parser with nested subcommands."""
    parser = argparse.ArgumentParser(description="Test parser")
    parser.add_argument("--foo", help="foo help")
    subparsers = parser.add_subparsers()
    subparser1 = subparsers.add_parser("foo")
    subparser1.add_argument("--foo", help="foo help")
    subparser2 = subparsers.add_parser("bar")
    subparser2.add_argument("config", help="config help")
    subparser2.add_argument("--bar", help="bar help")
    subparser3 = subparser2.add_subparsers()
    subparser3_1 = subparser3.add_parser("baz")
    subparser3_1.add_argument("config", help="config help")
    subparser3_1.add_argument("--baz", nargs="+", help="baz help")
    schema = template.CliParser(parser).extract_schema()
    assert schema["description"] == "Test parser"
    assert schema["subcommands"] == [
        {
            "name": "foo",
            "description": None,
            "arguments": [],
            "options": [{"name": "--foo", "type": "string", "help": "foo help"}],
            "subcommands": [],
        },
        {
            "name": "bar",
            "description": None,
            "arguments": [{"name": "config", "type": "string", "help": "config help"}],
            "options": [{"name": "--bar", "type": "string", "help": "bar help"}],
            "subcommands": [
                {
                    "name": "baz",
                    "description": None,
                    "arguments": [
                        {"name": "config", "type": "string", "help": "config help"}
                    ],
                    "options": [
                        {
                            "name": "--baz",
                            "type": "string",
                            "nargs": "+",
                            "help": "baz help",
                        }
                    ],
                    "subcommands": [],
                }
            ],
        },
    ]
