#


class AttachGenerate(object):
    _port: int

    def __init__(self, port: int):
        self._port = port

    @property
    def attach_id(self):
        return "{}".format(self._port)


class AttachParse(object):
    _attach_id: str

    def __init__(self, attach_id: str):
        self._attach_id = attach_id

    @property
    def port(self):
        return int(self._attach_id)
