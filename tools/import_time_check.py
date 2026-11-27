"""Fail if this checkout makes `import wandb` or the CLI slower than its base.

Two source trees are compared: the base (by default the merge base with the
pull request's target branch, checked out into a temporary git worktree) and
the current checkout. Both run against the same installed dependencies, with
`PYTHONPATH` selecting the tree, so no wheel is built and nothing is reinstalled.

Two signals are checked for each import:

1. Which modules get imported. New modules (present in the head run but not the
   base run) are deterministic evidence of a heavier import. The check fails
   when the modules that appeared cost more than `--budget-ms` of import time,
   net of the modules that disappeared, so moving code between modules does not
   trip it. This catches a new dependency or a package pulled in at import
   time regardless of how noisy the machine is.

2. Wall-clock import time. Base and head are measured in alternation after
   warm-up runs, so bytecode caches, page cache and machine load affect both
   equally. Interruptions only ever make a run slower, so the lower quartile of
   the samples is compared rather than the mean. The check fails when the head
   is slower by more than `--max-pct` and more than `--min-ms`, so a slow
   machine is not mistaken for a regression on a fast import and a tiny ratio
   is not flagged on noise.

Run locally from the repository root:

    python tools/import_time_check.py
    python tools/import_time_check.py --base origin/main --samples 30
"""

from __future__ import annotations

import argparse
import os
import pathlib
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass

IMPORTS = ("wandb", "wandb.cli.cli")


@dataclass
class Profile:
    """Import profile of one tree for one import statement."""

    seconds: float
    """Lower quartile of the timing samples."""

    self_ms: dict[str, float]
    """Median per-module self time across the importtime runs."""


def _run_python(
    tree: pathlib.Path, args: list[str]
) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"PYTHONPATH": str(tree)}
    # Run from a neutral directory so the current directory does not shadow the tree.
    return subprocess.run(
        [sys.executable, *args],
        cwd=tempfile.gettempdir(),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def _time_import(tree: pathlib.Path, module: str) -> float:
    code = (
        "import time; t = time.perf_counter(); "
        f"import {module}; print(time.perf_counter() - t)"
    )
    return float(_run_python(tree, ["-c", code]).stdout.strip())


def _module_self_times(tree: pathlib.Path, module: str) -> dict[str, float]:
    result = _run_python(tree, ["-X", "importtime", "-c", f"import {module}"])
    times: dict[str, float] = {}
    for line in result.stderr.splitlines():
        if not line.startswith("import time:") or "cumulative" in line:
            continue
        self_us, _, name = line[len("import time:") :].split("|")
        times[name.strip()] = int(self_us) / 1000
    return times


def profile(
    trees: dict[str, pathlib.Path], module: str, samples: int
) -> dict[str, Profile]:
    """Measure `module` in every tree, alternating between trees for each sample."""
    for tree in trees.values():
        for _ in range(2):  # warm up: compile bytecode, fill the page cache
            _time_import(tree, module)

    timings: dict[str, list[float]] = {name: [] for name in trees}
    importtimes: dict[str, list[dict[str, float]]] = {name: [] for name in trees}
    for i in range(samples):
        for name, tree in trees.items():
            timings[name].append(_time_import(tree, module))
            if i < 3:
                importtimes[name].append(_module_self_times(tree, module))

    profiles = {}
    for name in trees:
        modules = importtimes[name][0].keys()
        self_ms = {
            m: statistics.median(run.get(m, 0.0) for run in importtimes[name])
            for m in modules
        }
        lower_quartile = statistics.quantiles(timings[name], n=4)[0]
        profiles[name] = Profile(lower_quartile, self_ms)
    return profiles


def merge_base(ref: str) -> str:
    return subprocess.run(
        ["git", "merge-base", "HEAD", ref], capture_output=True, text=True, check=True
    ).stdout.strip()


def _format_ms(seconds: float) -> str:
    return f"{seconds * 1000:.0f} ms"


def _top(items: Iterable[tuple[str, float]], n: int = 8) -> str:
    rows = sorted(items, key=lambda kv: -kv[1])[:n]
    return "\n".join(f"    {ms:6.1f} ms  {name}" for name, ms in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--base",
        default=f"origin/{os.environ.get('GITHUB_BASE_REF') or 'main'}",
        help="Git ref whose merge base with HEAD is the baseline (default: %(default)s).",
    )
    parser.add_argument(
        "--base-tree",
        type=pathlib.Path,
        help="Use this checkout as the baseline instead of --base.",
    )
    parser.add_argument("--head-tree", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument(
        "--samples", type=int, default=20, help="Timing samples per tree and import."
    )
    parser.add_argument(
        "--max-pct",
        type=float,
        default=10.0,
        help="Fail above this percent slowdown (with --min-ms).",
    )
    parser.add_argument(
        "--min-ms",
        type=float,
        default=25.0,
        help="Fail above this absolute slowdown (with --max-pct).",
    )
    parser.add_argument(
        "--budget-ms",
        type=float,
        default=10.0,
        help="Fail when newly imported modules cost more than this, net of removed ones.",
    )
    args = parser.parse_args()

    worktree: pathlib.Path | None = None
    if args.base_tree is None:
        base_commit = merge_base(args.base)
        head_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        if base_commit == head_commit:
            print(f"HEAD is the merge base with {args.base}; nothing to compare.")
            return 0
        worktree = pathlib.Path(tempfile.mkdtemp(prefix="wandb-import-time-base-"))
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), base_commit],
            check=True,
            capture_output=True,
        )
        base_label = f"{args.base} ({base_commit[:9]})"
        base_tree = worktree
    else:
        base_tree = args.base_tree.resolve()
        base_label = str(base_tree)

    try:
        failures: list[str] = []
        summary = [
            "| import | base | head | change | new modules (net) |",
            "|---|---:|---:|---:|---:|",
        ]
        for module in IMPORTS:
            profiles = profile(
                {"base": base_tree, "head": args.head_tree.resolve()},
                module,
                args.samples,
            )
            base, head = profiles["base"], profiles["head"]
            delta = head.seconds - base.seconds
            pct = delta / base.seconds * 100

            new = {m: ms for m, ms in head.self_ms.items() if m not in base.self_ms}
            gone = {m: ms for m, ms in base.self_ms.items() if m not in head.self_ms}
            net_new_ms = sum(new.values()) - sum(gone.values())

            summary.append(
                f"| `import {module}` | {_format_ms(base.seconds)} | {_format_ms(head.seconds)} "
                f"| {pct:+.0f}% | {len(new)} ({net_new_ms:+.0f} ms) |"
            )
            if net_new_ms > args.budget_ms:
                failures.append(
                    f"`import {module}` imports {len(new)} new modules costing {net_new_ms:.0f} ms "
                    f"(budget {args.budget_ms:.0f} ms); heaviest:\n{_top(new.items())}"
                )
            if pct > args.max_pct and delta * 1000 > args.min_ms:
                grew = {
                    m: head.self_ms[m] - base.self_ms[m]
                    for m in head.self_ms.keys() & base.self_ms.keys()
                    if head.self_ms[m] - base.self_ms[m] >= 1.0
                }
                heavier = (
                    f"; modules that got heavier:\n{_top(grew.items())}" if grew else ""
                )
                failures.append(
                    f"`import {module}` is {pct:.0f}% ({_format_ms(delta)}) slower than the base "
                    f"(limit {args.max_pct:.0f}% and {args.min_ms:.0f} ms){heavier}"
                )

        report = "\n".join(summary)
        print(
            f"Import time against {base_label}, lower quartile of {args.samples} alternating runs:\n"
        )
        print(report)
        if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(step_summary, "a") as f:
                f.write(f"### Import time against {base_label}\n\n{report}\n\n")

        if failures:
            print("\nImport time check failed:\n")
            for failure in failures:
                print(f"- {failure}\n")
            print(
                "Import what a code path needs inside that code path, or under `if TYPE_CHECKING:` "
                "for annotations. To see the import tree: python -X importtime -c 'import wandb' 2>&1 | sort -t'|' -k2 -n | tail -40"
            )
            return 1
        print("\nImport time check passed.")
        return 0
    finally:
        if worktree is not None:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                check=False,
                capture_output=True,
            )


if __name__ == "__main__":
    sys.exit(main())
