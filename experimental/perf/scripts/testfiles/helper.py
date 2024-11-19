# json_generator/generator.py

import json
import random
import string

def generate_json_string(num_fields, field_size):
    # Convert to JSON-like string
    fields = generate_random_dict(num_fields, field_size)
    json_string = json.dumps(fields)
    return json_string


def generate_random_dict(num_fields, field_size):
    """
    Generates a JSON-like string with the specified number of fields and field sizes.
    
    Args:
        num_fields (int): The number of key-value pairs (fields) in the JSON.
        field_size (int): The size (in characters) of the field values (keys are 3-15 characters).
        
    Returns:
        str: A JSON-like string with the specified structure.
    """
    def random_key():
        # Generate a random key with a length "field_size"  characters
        return ''.join(random.choices(string.ascii_letters + string.digits + ' ', k=field_size))

    def random_value():
        # Generate a random integer value between 1 to 1M
        return random.randint(1, 10**6)

    # Generate the specified number of fields
    return {random_key(): random_value() for _ in range(num_fields)}

    
