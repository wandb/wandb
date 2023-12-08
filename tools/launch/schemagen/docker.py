import json
import re
import subprocess

from sympy import comp

# Step 1: Run 'docker run --help' in a subprocess and capture the output
result = subprocess.run(["docker", "run", "--help"], stdout=subprocess.PIPE, text=True)
output = result.stdout

# Step 2: Parse the output to find flags and their types
# Note: This is a simplified example, you'll need to adjust the regular expression
# and parsing logic based on the actual output format of 'docker run --help'
flags = {}
lines = output.splitlines()
idx = 0
while idx < len(lines):
    if lines[idx].strip().startswith("Options:"):
        break
    idx += 1
lines = lines[idx + 1 :]

# Regular expression to match the pattern of flags in the docker help output
flag_pattern = re.compile(r"(?:\s*(-\w),)?\s*--(\w[\w-]*)\s+(\w+)(?:\s{2,}(.+))?")

# Parsing the output and constructing the schema
flags = {}
for line in lines[idx:]:
    match = flag_pattern.match(line)
    if match:
        short_flag, long_flag, flag_type, description = match.groups()
        # Inferring the JSON type (you might need to adjust this logic)
        json_type = "string"  # Default type
        if flag_type == "list":
            json_type = "array"
        elif flag_type in ["int", "uint16"]:
            json_type = "integer"
        elif flag_type == "map":
            json_type = "object"
        elif flag_type == "bool":
            json_type = "boolean"

        # Adding to the flags dictionary
        flags[long_flag] = {
            "type": json_type,
            "description": description.strip() if description else "",
        }
        if short_flag:
            flags[short_flag.lstrip("-")] = flags[long_flag]


# Step 3: Construct the JSON schema
schema = {"type": "object", "properties": flags, "additionalProperties": False}

# Print the JSON schema
print(json.dumps(schema, indent=2))
