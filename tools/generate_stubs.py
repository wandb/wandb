r"""Generate stubs for public apis in wandb module.

Steps:
- __init__.pyi.template contains signatures of the public apis
    in the wandb module. Docstrings are replaced with placeholders
    of the form \"\"\"<source_file::location>\"\"\". For example:
    \"\"\"<wandb/__init__.py::init>\"\"\"
- Create __init__.pyi by replacing the placeholders with the
    docstrings from the corresponding source files.
- Run ruff to format and lint the generated stub.
- Check that the signatures of the apis in __init__.pyi
    matche the signatures in the source files.
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


def verify_signatures(wandb_root, output, template) -> int:
    output_path = wandb_root / output
    template_path = wandb_root / template

    output_content = output_path.read_text()
    template_content = template_path.read_text()

    functions_to_verify = extract_functions_from_template(template_content)

    output_tree = ast.parse(output_content)

    exit_code = 0

    for func_name, source_info in functions_to_verify.items():
        source_file, location = source_info.split("::", 1)
        source_path = wandb_root / source_file

        # Extract signature from source file
        source_content = source_path.read_text()
        source_tree = ast.parse(source_content)
        source_func = None
        is_method = False

        if "::" in location:
            class_name, method_name = location.split("::")
            for node in ast.walk(source_tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    for subnode in node.body:
                        if (
                            isinstance(subnode, ast.FunctionDef)
                            and subnode.name == method_name
                        ):
                            source_func = subnode
                            is_method = True
                            break
                    break
        else:
            for node in ast.walk(source_tree):
                if isinstance(node, ast.FunctionDef) and node.name == location:
                    source_func = node
                    break

        if source_func is None:
            print(f"Error: Could not find function '{func_name}' in {source_file}")
            continue

        # Extract signature from output file
        output_func = None
        for node in ast.walk(output_tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                output_func = node
                break

        if output_func is None:
            print(f"Error: Could not find function '{func_name}' in {output}")
            continue

        # Compare signatures
        source_args = source_func.args
        if is_method and source_args.args and source_args.args[0].arg == "self":
            # Remove 'self' parameter for methods
            source_args = ast.arguments(
                source_args.posonlyargs,
                source_args.args[1:],  # Remove 'self'
                source_args.vararg,
                source_args.kwonlyargs,
                source_args.kw_defaults,
                source_args.kwarg,
                source_args.defaults,
            )

        source_sig = ast.unparse(source_args)
        output_sig = ast.unparse(output_func.args)

        if source_sig != output_sig:
            print(f"Signature mismatch for '{func_name}':")
            print(f"  Source: {source_sig}")
            print(f"  Output: {output_sig}")
            exit_code = 1
        else:
            print(f"Signature match for '{func_name}'")

    return exit_code


if __name__ == "__main__":
    wandb_root = Path(__file__).parent.parent / "wandb"
    template = "__init__.template.pyi"
    output = "__init__.pyi"

    generate_stubs(wandb_root, template, output)
    lint_and_format_stub(wandb_root, output)
    exit_code = verify_signatures(wandb_root, output, template)

    exit(exit_code)
