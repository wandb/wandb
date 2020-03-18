from wandb.data_types import Table
from wandb.core import Error

class Visualize:
    def __init__(self, viz_id, value):
        self.viz_id = viz_id
        self.value = value

def visualize(viz_id, value):
    if not isinstance(value, Table):
        raise Error("visualize value must be Table, not {}".format(type(value).__name__))
    return Visualize(viz_id, value)
