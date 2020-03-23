

class Graph(object):

    def __init__(self):
        pass

    @classmethod
    def from_keras(cls, model):
        graph = cls()
        return graph

    def to_json(self):
        json_dict = dict()
        json_dict['_type'] = 'graph-file'
        return json_dict
