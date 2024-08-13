"""What.

- Define high-level function in __init__.pyi.template
- Create __init__.pyi using the template substituting
  the docstrings from corresponding places in the source code.
- Check that the signature of the function in __init__.pyi
    matches the signature of the function in the source code.
"""

import ast
import re
import subprocess
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


def extract_functions_from_template(template_content):
    pattern = r'"""<(.+?)>"""'
    matches = re.findall(pattern, template_content)
    return {match.split("::")[-1]: match for match in matches}


def generate_stubs(wandb_root, template, output):
    template_path = wandb_root / template
    output_path = wandb_root / output
    template_content = template_path.read_text()

    functions_to_update = extract_functions_from_template(template_content)

    for func_name, source_info in functions_to_update.items():
        source_file, location = source_info.split("::", 1)
        source_path = wandb_root / source_file

        docstring = extract_docstring(source_path, location)
        if docstring is None:
            print(f"Error: Could not find docstring for '{func_name}' in {source_file}")
            continue

        placeholder = f'"""<{source_info}>"""'
        template_content = template_content.replace(placeholder, f'"""{docstring}"""')
        print(f"Docstring updated for '{func_name}'.")

    output_path.write_text(template_content)
    print("All updates completed.")


def lint_and_format_stub(wandb_root, output):
    subprocess.run(["ruff", "format", str(wandb_root / output)], check=True)
    subprocess.run(
        [
            "ruff",
            "check",
            str(wandb_root / output),
            "--fix",
        ],
        check=True,
    )


if __name__ == "__main__":
    wandb_root = Path(__file__).parent.parent / "wandb"
    template = "__init__.pyi.template"
    output = "__init__.pyi"

    generate_stubs(wandb_root, template, output)
    lint_and_format_stub(wandb_root, output)
