class WBValue(object):
    """
    Abstract parent class for things that can be logged by wandb.log() and
    visualized by wandb.

    The objects will be serialized as JSON and always have a _type attribute
    that indicates how to interpret the other fields.
    """

    _type_mapping = None
    artifact_type = (
        None  # override this value to indicate the type which the subclass deserializes
    )

    def __init__(self):
        self._artifact_source = None

    def to_json(self, run_or_artifact):
        """Serializes the object into a JSON blob, using a run or artifact to store additional data.

        Args:
            run_or_artifact (wandb.Run | wandb.Artifact): the Run or Artifact for which this object should be generating
            JSON for - this is useful to to store additional data if needed.

        Returns:
            dict: JSON representation
        """
        raise NotImplementedError

    @classmethod
    def from_json(cls, json_obj, source_artifact):
        """Deserialize a `json_obj` into it's class representation. If additional resources were stored in the 
        `run_or_artifact` artifact during the `to_json` call, then those resources are expected to be in 
        the `source_artifact`.

        Args:
            json_obj (dict): A JSON dictionary to deserialize
            source_artifact (wandb.Artifact): An artifact which will hold any additional resources which were stored
            during the `to_json` function.
        """
        raise NotImplementedError

    @classmethod
    def with_suffix(cls, name, filetype="json"):
        """Helper function to return the name with suffix added if not already

        Args:
            name (str): the name of the file
            filetype (str, optional): the filetype to use. Defaults to "json".

        Returns:
            str: a filename which is suffixed with it's `artifact_type` followed by the filetype
        """
        if cls.artifact_type is not None:
            suffix = cls.artifact_type + "." + filetype
        else:
            suffix = filetype
        if not name.endswith(suffix):
            return name + "." + suffix
        return name

    @staticmethod
    def init_from_json(json_obj, source_artifact):
        """Looks through all subclasses and tries to match the json obj with the class which created it. It will then
        call that subclass' `from_json` method. Importantly, this function will set the return object's `source_artifact`
        attribute to the passed in source artifact. This is critical for artifact bookkeeping. If you choose to create
        a wandb.Value via it's `from_json` method, make sure to properly set this `artifact_source` to avoid data duplication.

        Args:
            json_obj (dict): A JSON dictionary to deserialize. It must contain a `_type` key. The value of
            this key is used to lookup the correct subclass to use.
            source_artifact (wandb.Artifact): An artifact which will hold any additional resources which were stored
            during the `to_json` function.

        Returns:
            wandb.Value: a newly created instance of a subclass of wandb.Value
        """
        class_option = WBValue.type_mapping().get(json_obj["_type"])
        if class_option is not None:
            obj = class_option.from_json(json_obj, source_artifact)
            obj.artifact_source = {"artifact": source_artifact}
            return obj

        return None

    @staticmethod
    def type_mapping():
        """Returns a map from `artifact_type` to subclass. Used to lookup correct types for deserialization.

        Returns:
            dict: dictionary of str:class
        """
        if WBValue._type_mapping is None:
            WBValue._type_mapping = {}
            frontier = [WBValue]
            explored = set([])
            while len(frontier) > 0:
                class_option = frontier.pop()
                explored.add(class_option)
                if class_option.artifact_type is not None:
                    WBValue._type_mapping[class_option.artifact_type] = class_option
                for subclass in class_option.__subclasses__():
                    if subclass not in explored:
                        frontier.append(subclass)
        return WBValue._type_mapping

    def __eq__(self, other):
        return super(WBValue, self).__eq__(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    @property
    def artifact_source(self):
        """Getter which returns the object's artifact source

        Returns:
            dict: {"artifact": wandb.Artifact, "name": str} the artifact from which this object was originally
            stored as well as the name (optional)
        """
        return self._artifact_source

    @artifact_source.setter
    def artifact_source(self, artifact_source):
        """Setter for artifact source

        Args:
            dict: {"artifact": wandb.Artifact, "name": str} the artifact from which this object was originally
            stored as well as the name (optional)
        """
        self._artifact_source = artifact_source