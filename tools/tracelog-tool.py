#!/usr/bin/env python
"""Parse tracelog output for analysis/diagrams.

Usage:
    ./client/tools/tracelog-tool.py path/to/rundir/
    ./client/tools/tracelog-tool.py output.txt
    ./client/tools/tracelog-tool.py output1.txt output2.txt
"""

import argparse
import pathlib
from typing import Any, List

DEFAULT_DIR: str = "wandb/latest-run/"

parser = argparse.ArgumentParser()
args = parser.parse_args()


class TracelogParser:
    def __init__(self) -> None:
        self._lines = []
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
            #FIXME: handle this
            return
        if direct == "<-":
            direct = "-->"
        ts = float(ts)
        if msg == "None":
            msg = "return_" + self._uuid_messages.get(uuid)
        self.add(ts, src, direct, dst, msg)

    def add(self, ts, src, arrow, dst, info):
        line = f"{src} {arrow} {dst}: {info}"
        self._lines.append((ts, line))

    def output(self) -> None:
        lines = sorted(self._lines)
        lines = [l for (ts, l) in lines]
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
        for l in lines:
            print(l)
        print("@enduml")

    def load(self, fname: str) -> None:
        with open(fname) as f:
            for l in f.readlines():
                self._parse(l)

    def loaddir(self, dname: str) -> None:
        flist = []
        for p in pathlib.Path(dname).iterdir():
            if not p.is_file():
                continue
            flist.append(p)

        for f in flist:
            self.load(f)


def main():
    parser = TracelogParser()
    # parser.load("out.txt")
    parser.loaddir(DEFAULT_DIR + "logs/")
    parser.output()


if __name__ == "__main__":
    main()
