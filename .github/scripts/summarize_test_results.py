"""Append the merged JUnit report to the GitHub Actions job summary."""

import html
import os
from pathlib import Path
from xml.etree import ElementTree


def summarize(report: Path) -> str:
    if not report.exists():
        return "### Test results\n\nNo JUnit report was produced. Check the test step for setup or collection failures.\n"

    try:
        cases = list(ElementTree.parse(report).iter("testcase"))
        seconds = sum(float(case.get("time", "0")) for case in cases)
    except (OSError, ElementTree.ParseError, ValueError) as error:
        return f"### Test results\n\nCould not read the JUnit report: <code>{html.escape(str(error))}</code>. Check the test step and uploaded report.\n"

    counts = {"passed": 0, "failure": 0, "error": 0, "skipped": 0}
    failed = []
    for case in cases:
        status = next(
            (
                tag
                for tag in ("error", "failure", "skipped")
                if case.find(tag) is not None
            ),
            "passed",
        )
        counts[status] += 1
        if status in ("failure", "error"):
            failed.append(case)

    summary = [
        "### Test results",
        "",
        "| Collected | Passed | Failed | Errors | Skipped |",
        "| ---: | ---: | ---: | ---: | ---: |",
        f"| {len(cases)} | {counts['passed']} | {counts['failure']} | {counts['error']} | {counts['skipped']} |",
        "",
        f"Recorded test time: {seconds:.1f} seconds (sum of JUnit test durations, not wall time).",
        "",
    ]

    # Bound both the number and size of failures to stay below GitHub's summary limit.
    for case in failed[:10]:
        name = "::".join(filter(None, (case.get("classname"), case.get("name"))))
        messages = []
        for result in case:
            if result.tag not in ("failure", "error"):
                continue
            message = result.get("message", "")
            details = (result.text or "").strip()
            if message and message not in details:
                details = f"{message}\n\n{details}"
            messages.append(details or result.tag)
        details = "\n\n".join(messages)
        if len(details) > 4000:
            details = (
                details[:4000]
                + "\n\n[Truncated; see the uploaded JUnit report for the full failure.]"
            )
        summary.extend(
            [
                f"<details><summary>{html.escape(name[:500] or 'Unnamed test')}</summary>",
                "",
                f"<pre>{html.escape(details)}</pre>",
                "",
                "</details>",
                "",
            ]
        )

    if len(failed) > 10:
        summary.append(
            f"Showing 10 of {len(failed)} failed tests. See the uploaded JUnit report for the rest.\n"
        )
    return "\n".join(summary) + "\n"


def main() -> None:
    summary = summarize(Path("test-results/junit.xml"))
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_path, "a", encoding="utf-8") as output:
            output.write(summary)
    else:
        print(summary, end="")  # noqa: T201


if __name__ == "__main__":
    main()
