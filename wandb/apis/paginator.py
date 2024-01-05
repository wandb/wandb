from typing import TYPE_CHECKING, Any, MutableMapping, Optional

if TYPE_CHECKING:
    from wandb_gql import Client


class Paginator:
    QUERY = None

    def __init__(
        self,
        client: "Client",
        variables: MutableMapping[str, Any],
        per_page: Optional[int] = None,
    ):
        self.client = client
        self.variables = variables
        # We don't allow unbounded paging
        self.per_page = per_page
        if self.per_page is None:
            self.per_page = 50
        self.objects = []
        self.index = -1
        self.last_response = None

    def __iter__(self):
        self.index = -1
        return self

    def __len__(self):
        if self.length is None:
            self._load_page()
        if self.length is None:
            raise ValueError("Object doesn't provide length")
        return self.length

    @property
    def length(self):
        raise NotImplementedError

    @property
    def more(self):
        raise NotImplementedError

    @property
    def cursor(self):
        raise NotImplementedError

    def convert_objects(self):
        raise NotImplementedError

    def update_variables(self):
        self.variables.update({"perPage": self.per_page, "cursor": self.cursor})

    def _load_page(self):
        if not self.more:
            return False
        self.update_variables()
        self.last_response = self.client.execute(
            self.QUERY, variable_values=self.variables
        )
        self.objects.extend(self.convert_objects())
        return True

    def __getitem__(self, index):
        loaded = True
        stop = index.stop if isinstance(index, slice) else index
        while loaded and stop > len(self.objects) - 1:
            loaded = self._load_page()
        return self.objects[index]

    def __next__(self):
        self.index += 1
        if len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
            if len(self.objects) <= self.index:
                raise StopIteration
        return self.objects[self.index]

    next = __next__
