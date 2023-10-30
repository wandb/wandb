import io
import os
import pathlib
from typing import TYPE_CHECKING, Optional, Sequence, Type, Union

from wandb import util
from wandb.sdk.lib import runid
from wandb.sdk.lib.paths import LogicalPath

from ._private import MEDIA_TMP
from .base_types.media import BatchableMedia, Media

if TYPE_CHECKING:  # pragma: no cover
    from typing import TextIO

    import rdkit.Chem  # type: ignore

    from wandb.sdk.artifacts.artifact import Artifact

    from ..wandb_run import Run as LocalRun

    RDKitDataType = Union[str, "rdkit.Chem.rdchem.Mol"]


class Molecule(BatchableMedia):
    """Wandb class for 3D Molecular data.

    Arguments:
        data_or_path: (string, io)
            Molecule can be initialized from a file name or an io object.
        caption: (string)
            Caption associated with the molecule for display.
    """

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
    SUPPORTED_RDKIT_TYPES = {"mol", "sdf"}
    _log_type = "molecule-file"

    def __init__(
        self,
        data_or_path: Union[str, "TextIO"],
        caption: Optional[str] = None,
        **kwargs: str,
    ) -> None:
        super().__init__()

        self._caption = caption

        if hasattr(data_or_path, "name"):
            # if the file has a path, we just detect the type and copy it from there
            data_or_path = data_or_path.name

        if hasattr(data_or_path, "read"):
            if hasattr(data_or_path, "seek"):
                data_or_path.seek(0)
            molecule = data_or_path.read()

            extension = kwargs.pop("file_type", None)
            if extension is None:
                raise ValueError(
                    "Must pass file_type keyword argument when using io objects."
                )
            if extension not in Molecule.SUPPORTED_TYPES:
                raise ValueError(
                    "Molecule 3D only supports files of the type: "
                    + ", ".join(Molecule.SUPPORTED_TYPES)
                )

            tmp_path = os.path.join(
                MEDIA_TMP.name, runid.generate_id() + "." + extension
            )
            with open(tmp_path, "w") as f:
                f.write(molecule)

            self._set_file(tmp_path, is_tmp=True)
        elif isinstance(data_or_path, str):
            extension = os.path.splitext(data_or_path)[1][1:]
            if extension not in Molecule.SUPPORTED_TYPES:
                raise ValueError(
                    "Molecule only supports files of the type: "
                    + ", ".join(Molecule.SUPPORTED_TYPES)
                )

            self._set_file(data_or_path, is_tmp=False)
        else:
            raise ValueError("Data must be file name or a file object")

    @classmethod
    def from_rdkit(
        cls,
        data_or_path: "RDKitDataType",
        caption: Optional[str] = None,
        convert_to_3d_and_optimize: bool = True,
        mmff_optimize_molecule_max_iterations: int = 200,
    ) -> "Molecule":
        """Convert RDKit-supported file/object types to wandb.Molecule.

        Arguments:
            data_or_path: (string, rdkit.Chem.rdchem.Mol)
                Molecule can be initialized from a file name or an rdkit.Chem.rdchem.Mol object.
            caption: (string)
                Caption associated with the molecule for display.
            convert_to_3d_and_optimize: (bool)
                Convert to rdkit.Chem.rdchem.Mol with 3D coordinates.
                This is an expensive operation that may take a long time for complicated molecules.
            mmff_optimize_molecule_max_iterations: (int)
                Number of iterations to use in rdkit.Chem.AllChem.MMFFOptimizeMolecule
        """
        rdkit_chem = util.get_module(
            "rdkit.Chem",
            required='wandb.Molecule needs the rdkit-pypi package. To get it, run "pip install rdkit-pypi".',
        )
        rdkit_chem_all_chem = util.get_module(
            "rdkit.Chem.AllChem",
            required='wandb.Molecule needs the rdkit-pypi package. To get it, run "pip install rdkit-pypi".',
        )

        if isinstance(data_or_path, str):
            # path to a file?
            path = pathlib.Path(data_or_path)
            extension = path.suffix.split(".")[-1]
            if extension not in Molecule.SUPPORTED_RDKIT_TYPES:
                raise ValueError(
                    "Molecule.from_rdkit only supports files of the type: "
                    + ", ".join(Molecule.SUPPORTED_RDKIT_TYPES)
                )
            # use the appropriate method
            if extension == "sdf":
                with rdkit_chem.SDMolSupplier(data_or_path) as supplier:
                    molecule = next(supplier)  # get only the first molecule
            else:
                molecule = getattr(rdkit_chem, f"MolFrom{extension.capitalize()}File")(
                    data_or_path
                )
        elif isinstance(data_or_path, rdkit_chem.rdchem.Mol):
            molecule = data_or_path
        else:
            raise ValueError(
                "Data must be file name or an rdkit.Chem.rdchem.Mol object"
            )

        if convert_to_3d_and_optimize:
            molecule = rdkit_chem.AddHs(molecule)
            rdkit_chem_all_chem.EmbedMolecule(molecule)
            rdkit_chem_all_chem.MMFFOptimizeMolecule(
                molecule,
                maxIters=mmff_optimize_molecule_max_iterations,
            )
        # convert to the pdb format supported by Molecule
        pdb_block = rdkit_chem.rdmolfiles.MolToPDBBlock(molecule)

        return cls(io.StringIO(pdb_block), caption=caption, file_type="pdb")

    @classmethod
    def from_smiles(
        cls,
        data: str,
        caption: Optional[str] = None,
        sanitize: bool = True,
        convert_to_3d_and_optimize: bool = True,
        mmff_optimize_molecule_max_iterations: int = 200,
    ) -> "Molecule":
        """Convert SMILES string to wandb.Molecule.

        Arguments:
            data: (string)
                SMILES string.
            caption: (string)
                Caption associated with the molecule for display
            sanitize: (bool)
                Check if the molecule is chemically reasonable by the RDKit's definition.
            convert_to_3d_and_optimize: (bool)
                Convert to rdkit.Chem.rdchem.Mol with 3D coordinates.
                This is an expensive operation that may take a long time for complicated molecules.
            mmff_optimize_molecule_max_iterations: (int)
                Number of iterations to use in rdkit.Chem.AllChem.MMFFOptimizeMolecule
        """
        rdkit_chem = util.get_module(
            "rdkit.Chem",
            required='wandb.Molecule needs the rdkit-pypi package. To get it, run "pip install rdkit-pypi".',
        )
        molecule = rdkit_chem.MolFromSmiles(data, sanitize=sanitize)
        if molecule is None:
            raise ValueError("Unable to parse the SMILES string.")

        return cls.from_rdkit(
            data_or_path=molecule,
            caption=caption,
            convert_to_3d_and_optimize=convert_to_3d_and_optimize,
            mmff_optimize_molecule_max_iterations=mmff_optimize_molecule_max_iterations,
        )

    @classmethod
    def get_media_subdir(cls: Type["Molecule"]) -> str:
        return os.path.join("media", "molecule")

    def to_json(self, run_or_artifact: Union["LocalRun", "Artifact"]) -> dict:
        json_dict = super().to_json(run_or_artifact)
        json_dict["_type"] = self._log_type
        if self._caption:
            json_dict["caption"] = self._caption
        return json_dict

    @classmethod
    def seq_to_json(
        cls: Type["Molecule"],
        seq: Sequence["BatchableMedia"],
        run: "LocalRun",
        key: str,
        step: Union[int, str],
    ) -> dict:
        seq = list(seq)

        jsons = [obj.to_json(run) for obj in seq]

        for obj in jsons:
            expected = LogicalPath(cls.get_media_subdir())
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
            "captions": Media.captions(seq),
        }
