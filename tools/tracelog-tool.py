#!/usr/bin/env python
"""Parse tracelog output for analysis/diagrams.

NOTE: tracelog is still in development.

Usage:
    ./wandb/tools/tracelog-tool.py
    ./wandb/tools/tracelog-tool.py --logdir logdir/
    ./wandb/tools/tracelog-tool.py --format plantuml
"""

import argparse
import pathlib
import sys
from dataclasses import dataclass
from typing import List


@dataclass
class SequenceItem:
    ts: float
    src: str
    request: bool
    dst: str
    info: str


class TracelogParser:
    def __init__(self) -> None:
        self._items: List[SequenceItem] = []
        self._uuid_messages = dict()

    def _parse(self, line: str) -> None:
        line = line.strip()
        index = line.find("TRACELOG(")
        if index < 0:
            return
        line = line[index:]
        items = line.split()
        if len(items) != 10:
            return
        # ['TRACELOG(1)', '<-', '185542.522061', 'fd1e0e9f4d3f3520', 'dequeue', 'result_q', 'MsgRouterThr', 'poll_exit_response', '69aed18a893a49d182c7a13b498f805f', '-']
        magic, direct, ts, msg_id, op, resource, thr, msg, uuid, stream = items
        self._uuid_messages.setdefault(uuid, msg)
        if magic != "TRACELOG(1)":
            return
        thr = thr.replace("-", "_")
        if op == "queue":
            src = thr
            dst = resource
        elif op == "dequeue":
            dst = thr
            src = resource
        else:
            # TODO: handle this
            return
        request = True
        if direct == "<-":
            request = False
        ts = float(ts)
        if msg == "None":
            msg = "return_" + self._uuid_messages.get(uuid)
        item = SequenceItem(ts=ts, src=src, request=request, dst=dst, info=msg)
        self.add(item)

    def add(self, item: SequenceItem):
        self._items.append(item)

    def output_plantuml(self) -> None:
        lines = []
        for item in self._items:
            line = f"{item.src} --> {item.dst}: {item.info}"
            lines.append((item.ts, line))
        print("@startuml")
        header = """
!theme crt-amber
skinparam responseMessageBelowArrow true
box "User Process"
participant User as MainThread
control router as MsgRouterThr
control check_stop as ChkStopThr
control net_stat as NetStatThr
end box

queue record_q as record_q
queue result_q as result_q

box "Internal Process"
control handler as HandlerThread
control stats as StatsThr
queue send_q as send_q
queue write_q as write_q
control writer as WriterThread
control sender as SenderThread
end box
        """
        print(header)
        # TODO: move to common place (sorted sequence items)
        for line in [l for (ts, l) in sorted(lines)]:
            print(line)
        print("@enduml")

    def output_mermaid(self) -> None:
        lines = []
        for item in self._items:
            line = f"{item.src} ->> {item.dst}: {item.info}"
            lines.append((item.ts, line))

        header = """
sequenceDiagram
participant MainThread as User
participant MsgRouterThr as router
participant ChkStopThr as check_stop
participant NetStatThr as net_stat

participant record_q as record_q
participant result_q as result_q

participant HandlerThread as handler
participant StatsThr as stats
participant send_q as send_q
participant write_q as write_q
participant WriterThread as writer
participant SenderThread as sender
        """
        print(header)
        # TODO: move to common place (sorted sequence items)
        for line in [l for (ts, l) in sorted(lines)]:
            print(line)

    def load(self, fname: str) -> None:
        with open(fname) as f:
            for line in f.readlines():
                self._parse(line)

    def loaddir(self, dname: str) -> None:
        flist = []
        for p in pathlib.Path(dname).iterdir():
            if not p.is_file():
                continue
            flist.append(p)

        for f in flist:
            self.load(f)


def main():
    argparser = argparse.ArgumentParser()
    argparser.add_argument("--logdir", default="wandb/latest-run/logs/")
    argparser.add_argument("--format", default="mermaid")
    args = argparser.parse_args()

    parser = TracelogParser()
    parser.loaddir(args.logdir)
    if args.format == "plantuml":
        parser.output_plantuml()
    elif args.format == "mermaid":
        parser.output_mermaid()
    else:
        print(f"Unknown format: {args.format}")
        sys.exit(1)


if __name__ == "__main__":
    main()
