import pathlib
from .media import Media
from typing import Union, Optional, TextIO

# import rdkit.Chem


class Molecule(Media):
    OBJ_TYPE = "molecule-file"
    RELATIVE_PATH = pathlib.Path("media") / "molecule"

    SUPPORTED_TYPES = {
        "pdb",
        "pqr",
        "mmcif",
        "mcif",
        "cif",
        "sdf",
        "sd",
        "gro",
        "mol2",
        "mmtf",
    }

    # SUPPORTED_RDKIT_TYPES = {"mol", "sdf"}

    _caption: Optional[str]

    def __init__(
        self,
        data_or_path,
        caption: Optional[str] = None,
        file_type: Optional[str] = None,
        **kwargs,
    ) -> None:
        self._caption = caption
        if isinstance(data_or_path, pathlib.Path):
            self.from_path(data_or_path)
        elif isinstance(data_or_path, str):
            self.from_string(data_or_path, file_type=file_type)
        elif hasattr(data_or_path, "read"):
            self.from_buffer(data_or_path, file_type)
        else:
            raise ValueError("Unsupported type: {}".format(type(data_or_path)))

    def from_buffer(self, buffer: TextIO, file_type: Optional[str] = None) -> None:
        if hasattr(buffer, "seek"):
            buffer.seek(0)
        mol = buffer.read()
        if file_type is None or file_type not in self.SUPPORTED_TYPES:
            raise ValueError(f"Unsupported file type: {file_type}")
        self._format = file_type
        self._source_path = self._generate_temp_path(suffix=f".{self._format}")
        self._is_temp_path = True
        with open(self._source_path, "w") as f:
            f.write(mol)

    def from_path(self, path: Union[str, pathlib.Path]) -> None:
        self._source_path = pathlib.Path(path).absolute()
        self._format = self._source_path.suffix[1:].lower()
        assert (
            self._format in self.SUPPORTED_TYPES
        ), f"Unsupported file type: {self._format}"
        self._is_temp_path = False
        self._sha256 = self._compute_sha256(self._source_path)
        self._size = self._source_path.stat().st_size

    def from_string(self, data_or_path: str, file_type: Optional[str] = None) -> None:
        path = pathlib.Path(data_or_path)
        if path.suffix[:1] in self.SUPPORTED_TYPES:
            self.from_path(path)
        else:

