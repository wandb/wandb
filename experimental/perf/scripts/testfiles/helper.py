import json
import os
import random
import string


def generate_random_dict(num_fields: int, field_size: int) -> dict:
    """Generates a JSON-like dict with the specified number of fields and field sizes.

    Args:
        num_fields (int): The number of key-value pairs (fields) in the JSON.
        field_size (int): The size (in characters) of the field values.

    Returns:
        str: A JSON-like string with the specified structure.
    """

    def random_key():
        # Generate a random key with a length "field_size"  characters
        return "".join(
            random.choices(string.ascii_letters + string.digits + "_", k=field_size)
        )

    # Generate the specified number of fields
    return {random_key(): random.randint(1, 10**6) for _ in range(num_fields)}


def append_to_json(file_path: str, key: str, value):
    """Appends a key-value pair to a JSON file. Creates the file if it doesn't exist.

    Args:
        file_path (str): Path to the JSON file.
        key (str): The key to add to the JSON file.
        value: The value associated with the key.
    """
    data = {}

    # Check if the file exists and is not empty
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        with open(file_path) as file:
            try:
                data = json.load(file)
            except json.JSONDecodeError:
                pass  # If the file is invalid, treat it as empty

    # Update the dictionary
    data[key] = value

    # Write the updated dictionary back to the file
    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)
