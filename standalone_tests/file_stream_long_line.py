#!/usr/bin/env python

"""Test streaming a file with a really long line to the back end.

This sends a history row whose size is (currently) exactly at the limit to make
sure the back end handles it properly. It looks unrealistic, but it is totally
possible if the user logs a lot of data.
"""

import sys
import wandb
import time
wandb.init()
wandb.log({'b': 12354})
time.sleep(5)
wandb.log({'a': 'l' * (4194217 - 100 * 1024)})
wandb.log({'c': 'l' * (4*1024*1024)})
