class Classes(Media):
    artifact_type = "classes"

    def __init__(self, class_set):
        """Classes is holds class metadata intended to be used in concert with other objects when visualizing artifacts

        Args:
            class_set (list): list of dicts in the form of {"id":int|str, "name":str}
        """
        super(Classes, self).__init__()
        self._class_set = class_set
        # TODO: validate

    @classmethod
    def from_json(cls, json_obj, source_artifact):
        return cls(json_obj.get("class_set"))

    def to_json(self, artifact):
        json_obj = super(Classes, self).to_json(artifact)
        json_obj["_type"] = Classes.artifact_type
        json_obj["class_set"] = self._class_set
        return json_obj

    def __ne__(self, other):
        return not self.__eq__(other)

    def __eq__(self, other):
        return self._class_set == other._class_set