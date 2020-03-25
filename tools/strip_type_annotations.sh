cp wandb/sdk/*.py wandb/sdk_py27/
rm wandb/sdk_py27/*_test.py
python3 -m libcst.tool codemod --no-format remove_types.RemoveTypesTransformer wandb/sdk_py27/*.py
