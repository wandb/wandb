r"""Generate and verify stubs for public APIs in the wandb module.

This script automates the process of creating and validating type stub files
for the wandb module's public APIs. It performs the following steps:

1. Generate stubs:
   - Read the __init__.template.pyi file, which contains signatures of public APIs
     with placeholders for docstrings.
   - Extract docstrings from corresponding source files.
   - Replace placeholders in the template with the extracted docstrings.
   - Write the generated content to __init__.pyi.

2. Lint and format:
   - Use ruff to format the generated __init__.pyi file.
   - Run ruff to lint and automatically fix minor issues in the generated stub.

3. Verify signatures:
   - Compare the signatures of APIs in the generated __init__.pyi
     with the signatures in the original source files.
   - Report any mismatches found during the verification process.

Usage:
    Run this script from the command line:
    $ python generate_stubs.py

    The script assumes it's located in the 'wandb' parent directory and will
    look for the 'wandb' directory relative to its location.

Dependencies:
    - Python 3.7+
    - ruff (for linting and formatting)

Note:
    Ensure that the wandb module source code and the __init__.template.pyi
    file are up to date before running this script.
"""

import ast
import re
import subprocess
from pathlib import Path
from typing import Optional


def extract_docstring(file_path: Path, location: str) -> Optional[str]:
    """Extract the docstring for a given function or method from a source file.

    Args:
        file_path (Path): The path to the source file.
        location (str): The location of the function or method in the format
                        "ClassName::method_name" or "function_name".

    Returns:
        Optional[str]: The extracted docstring, or None if not found.
    """
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


def extract_functions_from_template(template_content: str) -> dict[str, str]:
    """Extracts function names and their source information from the template.

    Args:
        template_content (str): The content of the template file.

    Returns:
        Dict[str, str]: A dictionary mapping function names to their source information.
    """
    pattern = r'"""<(.+?)>"""'
    matches = re.findall(pattern, template_content)
    return {match.split("::")[-1]: match for match in matches}


def generate_stubs(wandb_root: Path, template: str, generated_stub: str) -> None:
    """Generate stubs for public APIs in the wandb module.

    Args:
        wandb_root (Path): The root directory of the wandb module.
        template (str): The name of the template file.
        generated_stub (str): The name of the output file.
    """
    template_path = wandb_root / template
    output_path = wandb_root / generated_stub
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
        template_content = template_content.replace(placeholder, f'"""{docstring}\n"""')
        print(f"Docstring updated for '{func_name}'.")

    output_path.write_text(template_content)
    print("All updates completed.")


def lint_and_format_stub(wandb_root: Path, generated_stub: str) -> None:
    """Lint and format the generated stub file using ruff.

    Args:
        wandb_root (Path): The root directory of the wandb module.
        generated_stub (str): The name of the output file.
    """
    subprocess.run(["ruff", "format", str(wandb_root / generated_stub)], check=True)
    subprocess.run(
        [
            "ruff",
            "check",
            str(wandb_root / generated_stub),
            "--fix",
        ],
        check=True,
    )


def verify_signatures(wandb_root: Path, generated_stub: str, template: str) -> int:
    """Verifies that generated stubs match their source signatures.

    Args:
        wandb_root (Path): The root directory of the wandb module.
        generated_stub (str): The name of the output file.
        template (str): The name of the template file.

    Returns:
        int: Exit code (0 for success, 1 for mismatch).
    """
    output_path = wandb_root / generated_stub
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
            print(f"Error: Could not find function '{func_name}' in {generated_stub}")
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
    generated_stub = "__init__.pyi"

    generate_stubs(wandb_root, template, generated_stub)
    lint_and_format_stub(wandb_root, generated_stub)
    exit_code = verify_signatures(wandb_root, generated_stub, template)

    exit(exit_code)
