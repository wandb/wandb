#!/bin/bash
set -e

DEST="wandb/sdk_py27/"
DEST_TMP="wandb/sdk_py27_tmp/"

dest=$DEST
check=false

if [ "$1" == "--check" ]; then
	check=true
	dest=$DEST_TMP
fi

if [ "$dest" == "" -o "$dest" == "/" ]; then
	echo "SAFETY CHECK"
	exit 1
fi

mkdir -p $dest
rm -r ${dest}
mkdir $dest

cp wandb/sdk/*.py $dest
python3 -m libcst.tool codemod --no-format remove_types.RemoveTypesTransformer $dest/*.py

if $check; then
	#diff -q $DEST $DEST_TMP | egrep "[.]py$"
	set +e
	diff --exclude="*.pyc" --exclude="__pycache__" -q $DEST $DEST_TMP
	result="$?"
	set -e
	rm ${dest}*
	rmdir $dest
	if [ $result -ne 0 ]; then
		echo "ERROR: codemod check failed."
		exit 1
	fi
fi
