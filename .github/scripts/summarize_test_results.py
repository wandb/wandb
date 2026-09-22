"""Appends a summary of the merged JUnit report to the GitHub Actions job summary."""

import html
import os
from pathlib import Path
from xml.etree import ElementTree

MAX_FAILURES = 10


def summarize(report: Path) -> str:
    if not report.exists():
        return "No JUnit report was produced; check the test step for errors.\n"

    cases = list(ElementTree.parse(report).iter("testcase"))
    failed = [
        case
        for case in cases
        if case.find("failure") is not None or case.find("error") is not None
    ]
    skipped = sum(case.find("skipped") is not None for case in cases)
    lines = [
        "| Tests | Passed | Failed | Skipped |",
        "| ---: | ---: | ---: | ---: |",
        f"| {len(cases)} | {len(cases) - len(failed) - skipped} | {len(failed)} | {skipped} |",
        "",
    ]
    for case in failed[:MAX_FAILURES]:
        name = "::".join(filter(None, (case.get("classname"), case.get("name"))))
        result = next(child for child in case if child.tag in ("failure", "error"))
        details = (result.text or result.get("message") or "").strip()[:4000]
        lines += [
            f"<details><summary>{html.escape(name)}</summary>",
            "",
            f"<pre>{html.escape(details)}</pre>",
            "</details>",
            "",
        ]
    if len(failed) > MAX_FAILURES:
        lines.append(
            f"Showing {MAX_FAILURES} of {len(failed)} failures;"
            " the uploaded report has the rest.\n"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
        summary.write(summarize(Path("test-results/junit.xml")))
