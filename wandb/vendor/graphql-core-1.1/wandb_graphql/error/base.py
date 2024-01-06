from ..language.location import get_location


class GraphQLError(Exception):
    __slots__ = 'message', 'nodes', 'stack', 'original_error', '_source', '_positions'

    def __init__(self, message, nodes=None, stack=None, source=None, positions=None):
        super(GraphQLError, self).__init__(message)
        self.message = message
        self.nodes = nodes
        self.stack = stack
        self._source = source
        self._positions = positions

    @property
    def source(self):
        if self._source:
            return self._source
        if self.nodes:
            node = self.nodes[0]
            return node and node.loc and node.loc.source

    @property
    def positions(self):
        if self._positions:
            return self._positions
        if self.nodes is not None:
            node_positions = [node.loc and node.loc.start for node in self.nodes]
            if any(node_positions):
                return node_positions

    def reraise(self):
        if self.stack:
            raise self.with_traceback(self.stack)
        else:
            raise self

    @property
    def locations(self):
        source = self.source
        if self.positions and source:
            return [get_location(source, pos) for pos in self.positions]
