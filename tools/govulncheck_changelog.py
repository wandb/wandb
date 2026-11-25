"""Note the known vulnerabilities fixed by a Go dependency update in CHANGELOG.unreleased.md.

The Update Go Dependencies workflow runs `govulncheck -scan module -json` in
core/ before and after updating Go and the Go dependencies, then runs this
script on the two outputs from the repository root.
"""

import argparse
import json
import pathlib
import re
import sys


def _vulns(path: str) -> tuple[dict[str, dict], dict[str, str]]:
    """Return the OSV entries and the affected module of each finding."""
    text = pathlib.Path(path).read_text()
    decoder = json.JSONDecoder()
    osv: dict[str, dict] = {}
    modules: dict[str, str] = {}
    pos = 0
    while pos < len(text):
        message, pos = decoder.raw_decode(text, pos)
        pos += len(text[pos:]) - len(text[pos:].lstrip())
        if "osv" in message:
            osv[message["osv"]["id"]] = message["osv"]
        if "finding" in message:
            finding = message["finding"]
            modules[finding["osv"]] = finding["trace"][0]["module"]
    return osv, modules


def _link(osv: dict) -> str:
    aliases = osv.get("aliases", [])
    cve = next((a for a in aliases if a.startswith("CVE-")), None)
    name = cve or (aliases[0] if aliases else osv["id"])
    return f"[{name}](https://pkg.go.dev/vuln/{osv['id']})"


def _join(items: list[str]) -> str:
    return " and ".join(filter(None, [", ".join(items[:-1]), *items[-1:]]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "before", help="govulncheck -scan module -json output before the update"
    )
    parser.add_argument("after", help="the same output after the update")
    parser.add_argument(
        "--pr-url", required=True, help="URL of the pull request making the update"
    )
    args = parser.parse_args()

    osv, modules = _vulns(args.before)
    _, remaining = _vulns(args.after)
    if remaining:
        print(
            "Known vulnerabilities remain after the update:",
            *sorted(remaining),
            file=sys.stderr,
        )
    fixed = sorted(set(modules) - set(remaining), key=lambda i: _link(osv[i]))
    if not fixed:
        return

    gomod = pathlib.Path("core/go.mod").read_text()
    requires = "".join(
        re.findall(r"^require \(\n(.*?)^\)", gomod, re.MULTILINE | re.DOTALL)
    )
    names = {"stdlib": "Go " + re.findall(r"^go (\S+)$", gomod, re.MULTILINE)[0]}
    for module, version in re.findall(r"^\s*(\S+) (v\S+)", requires, re.MULTILINE):
        names[module] = f"`{module}` {version}"
    built_with = _join(
        [names[m] for m in dict.fromkeys(modules[i] for i in fixed) if m in names]
    )
    fixes = _join([_link(osv[i]) for i in fixed])
    entry = f"- `wandb-core` is built with {built_with or 'updated Go dependencies'}, which fixes {fixes} ({args.pr_url})"

    changelog = pathlib.Path("CHANGELOG.unreleased.md")
    text = changelog.read_text().rstrip("\n")
    # ponytail: Security is the last section in Keep a Changelog order, so the entry goes at the end.
    if "### Security" not in text:
        text += "\n\n### Security"
    if text.endswith("### Security"):
        text += "\n"
    changelog.write_text(f"{text}\n{entry}\n")
    print(entry)


if __name__ == "__main__":
    main()
