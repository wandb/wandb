"""What.

- Define high-level function in __init__.pyi.template
- Create __init__.pyi using the template substituting
  the docstrings from corresponding places in the source code.
- Check that the signature of the function in __init__.pyi
    matches the signature of the function in the source code.
"""

import ast
from pathlib import Path


def extract_docstring(file_path, location):
    content = file_path.read_text()
    tree = ast.parse(content)

    if "::" in location:
        class_name, method_name = location.split("::")
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for subnode in node.body:
                    if (
                        isinstance(subnode, ast.FunctionDef)
                        and subnode.name == method_name
                    ):
                        return ast.get_docstring(subnode)
    else:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == location:
                return ast.get_docstring(node)

    return None


def update_template_file(wandb_root, template, output, functions_to_update):
    template_path = wandb_root / template
    output_path = wandb_root / output
    content = template_path.read_text()

    for func_name, source_info in functions_to_update.items():
        source_file, location = source_info.split("::", 1)
        source_path = wandb_root / source_file

        docstring = extract_docstring(source_path, location)
        if docstring is None:
            print(f"Error: Could not find docstring for '{func_name}' in {source_file}")
            continue

        placeholder = f'"""<{source_info}>"""'
        content = content.replace(placeholder, f'"""{docstring}"""')
        print(f"Docstring updated for '{func_name}'.")

    output_path.write_text(content)
    print("All updates completed.")


def lint_and_format_stub() -> str:
    import subprocess

    subprocess.run(["ruff", "format", str(wandb_root / output)], check=True)
    subprocess.run(
        [
            "ruff",
            "check",
            str(wandb_root / output),
            "--fix",
            # "--ignore",
            # "UP007,F821,UP006,UP037",
        ],
        check=True,
    )


# Usage
wandb_root = Path(__file__).parent.parent / "wandb"
template = "__init__.pyi.template"
output = "__init__.pyi"

functions_to_update = {
    "init": "sdk/wandb_init.py::init",
    "setup": "sdk/wandb_setup.py::setup",
    "log": "sdk/wandb_run.py::Run::log",
}

update_template_file(wandb_root, template, output, functions_to_update)
lint_and_format_stub()
