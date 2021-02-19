from ._CustomArtifactType import _CustomArtifactType


class Dataset(_CustomArtifactType):
    @staticmethod
    def get_type_name() -> str:
        return "dataset"
