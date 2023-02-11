#!/usr/bin/env python


from dataclasses import dataclass
from junitparser import JUnitXml, Element, Attr


# fname = "data/407321_3_test-results_junit-yea.xml"

class CustomElement(Element):
    _tag = 'properties'


class PropElement(Element):
    _tag = 'property'
    name = Attr()
    value = Attr()


@dataclass
class PerfReport:
    name: str
    value: str


def parse_junit_perf(fname):
    xml = JUnitXml.fromfile(fname)
    for suite in xml:
        for case in suite:
            for properties in case.iterchildren(CustomElement):
                for prop in properties.iterchildren(PropElement):
                    # print("got", prop.name, prop.value)
                    yield PerfReport(name=prop.name, value=prop.value)


if __name__ == "__main__":
    fname = "data/425434_0_test-results_junit-yea.xml"
    reports = parse_junit_perf(fname)
    print("reports", list(reports))
