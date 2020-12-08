class Molecule(BatchableMedia):
    """
        Wandb class for Molecular data

        Arguments:
            data_or_path (string, io):
                Molecule can be initialized from a file name or an io object.
    """

    SUPPORTED_TYPES = set(
        ["pdb", "pqr", "mmcif", "mcif", "cif", "sdf", "sd", "gro", "mol2", "mmtf"]
    )

    def __init__(self, data_or_path, **kwargs):
        super(Molecule, self).__init__(**kwargs)

        if hasattr(data_or_path, "name"):
            # if the file has a path, we just detect the type and copy it from there
            data_or_path = data_or_path.name

        if hasattr(data_or_path, "read"):
            if hasattr(data_or_path, "seek"):
                data_or_path.seek(0)
            molecule = data_or_path.read()

            extension = kwargs.pop("file_type", None)
            if extension == None:
                raise ValueError(
                    "Must pass file type keyword argument when using io objects."
                )
            if extension not in Molecule.SUPPORTED_TYPES:
                raise ValueError(
                    "Molecule 3D only supports files of the type: "
                    + ", ".join(Molecule.SUPPORTED_TYPES)
                )

            tmp_path = os.path.join(
                MEDIA_TMP.name, util.generate_id() + "." + extension
            )
            with open(tmp_path, "w") as f:
                f.write(molecule)

            self._set_file(tmp_path, is_tmp=True)
        elif isinstance(data_or_path, six.string_types):
            path = data_or_path
            try:
                extension = os.path.splitext(data_or_path)[1][1:]
            except:
                raise ValueError("File type must have an extension")
            if extension not in Molecule.SUPPORTED_TYPES:
                raise ValueError(
                    "Molecule only supports files of the type: "
                    + ", ".join(Molecule.SUPPORTED_TYPES)
                )

            self._set_file(data_or_path, is_tmp=False)
        else:
            raise ValueError("Data must be file name or a file object")

    @classmethod
    def get_media_subdir(self):
        return os.path.join("media", "molecule")

    def to_json(self, run):
        json_dict = super(Molecule, self).to_json(run)
        json_dict["_type"] = "molecule-file"
        if self._caption:
            json_dict["caption"] = self._caption
        return json_dict

    @classmethod
    def seq_to_json(cls, molecule_list, run, key, step):
        molecule_list = list(molecule_list)

        jsons = [obj.to_json(run) for obj in molecule_list]

        for obj in jsons:
            expected = util.to_forward_slash_path(cls.get_media_subdir())
            if not obj["path"].startswith(expected):
                raise ValueError(
                    "Files in an array of Molecule's must be in the {} directory, not {}".format(
                        cls.get_media_subdir(), obj["path"]
                    )
                )

        return {
            "_type": "molecule",
            "filenames": [obj["path"] for obj in jsons],
            "count": len(jsons),
            "captions": Media.captions(molecule_list),
        }
