"""Script to set testsuite properties in a junit.xml file.

Used by nox testing sessions.
"""

import argparse

import junitparser

parser = argparse.ArgumentParser(
    description="Script to set testsuite properties in a junit.xml file.",
)
parser.add_argument(
    "--add",
    dest="props",
    action="append",
    help="properties to add in the format <name>=<value>",
)
parser.add_argument("file", help="junitxml file to modify")
args = parser.parse_args()

props: "list[str]" = args.props
file: str = args.file

xml = junitparser.JUnitXml.fromfile(file)

for prop in props:
    name, value = prop.split("=")

    if isinstance(xml, junitparser.TestSuite):
        xml.add_property(name, value)
    else:
        for suite in xml:
            suite.add_property(name, value)

xml.write()
