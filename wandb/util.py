import json
import numpy as np

class WandBJSONEncoder(json.JSONEncoder):
    """A JSON Encoder that handles some extra types."""
    def default(self, obj):
        # TODO: Some of this is just guessing. Be smarter.
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.generic):
            return np.asscalar(obj)
        if isinstance(obj, bytes):
            return obj.decode('utf-8')
        return json.JSONEncoder.default(self, obj)

def json_dumps_safer(obj, **kwargs):
    """Convert obj to json, with some extra encodable types."""
    return json.dumps(obj, cls=WandBJSONEncoder, **kwargs)

def make_json_if_not_number(v):
    """If v is not a basic type convert it to json."""
    if isinstance(v, (float, int)):
        return v
    return util.json_dumps_safer(v)