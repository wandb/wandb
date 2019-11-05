#!/usr/bin/env python

"""Test streaming a file with a really long line to the back end.

This sends a history row whose size is (currently) exactly at the limit to make
sure the back end handles it properly. It looks unrealistic, but it is totally
possible if the user logs a lot of data.
"""

import sys
import wandb
wandb.init()
wandb.log({'a': 'l' * (4194217 - 100 * 1024)})