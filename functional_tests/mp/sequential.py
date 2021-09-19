#!/usr/bin/env python
"""Test sequential runs."""

import sys

import wandb


run1 = wandb.init()
run1.log(dict(r1a=1, r2a=2))
print("first run")
print("another line 1st run", end="")
print("my error the one", file=sys.stderr, end="")
print("continue one", end="")
print("cont my error the one", file=sys.stderr)
print("extra error the one", file=sys.stderr)
print("continue one again")
print("more 1st run")
run1.finish()

run2 = wandb.init()
run2.log(dict(r1a=11, r2b=22))
print("second run")
print("another line 2nd run", end="")
print("my error the two", file=sys.stderr, end="")
print("continue two", end="")
print("cont my error the two", file=sys.stderr)
print("extra error the two", file=sys.stderr)
print("continue two again")
print("more 2nd run")
# run2 will get finished with the script
