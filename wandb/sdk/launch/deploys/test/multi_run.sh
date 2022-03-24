#!/bin/bash
echo "Running multi_run.sh"
python test1.py $@ > /dev/null;
echo "Running second job"
python test2.py $@ > /dev/null;
echo "Done"