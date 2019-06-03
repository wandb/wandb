#!/usr/bin/env python

"""Example script for uploading a set of images into a run so
so that we can refer to them from other runs.

This isn't what we'd recommend users do, just something for
us to do internally for the time being to test that kind
of functionality.
"""

from __future__ import print_function

import os
import shutil
import subprocess

import wandb
import wandb.apis


def main():
	run = wandb.init()

	# download the data if it doesn't exist
	if not os.path.exists("simpsons"):
	    print("Downloading Simpsons dataset...")
	    subprocess.check_output(
	        "curl https://storage.googleapis.com/wandb-production.appspot.com/mlclass/simpsons.tar.gz | tar xvz", shell=True)

	shutil.copytree(os.path.join('simpsons', 'test'), os.path.join(run.dir, 'simpsons', 'test'))

	print()
	print()
	print()
	print()
	print('After this run, the simpsons test images will be available at eg.')
	print()
	print('{}/{}/simpsons/test/abraham_grampa_simpson/img_1027.jpg'.format(wandb.apis.InternalApi().api_url, run.path))
	print()
	print()
	print()
	print()


if __name__ == '__main__':
	main()