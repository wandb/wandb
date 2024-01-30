import pathlib
import runpy


def test_benchmark_1():
    # Define the global variables to be used in the script
    init_globals = {"my_var": "Hello, World!"}

    # Run the script with the specified globals
    path = pathlib.Path(__file__).parent / "bench.py"
    output_namespace = runpy.run_path(
        path, init_globals=init_globals, run_name="__main__"
    )
    print(output_namespace["my_var"])
