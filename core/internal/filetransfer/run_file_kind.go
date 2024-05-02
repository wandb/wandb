package filetransfer

import "github.com/wandb/wandb/core/pkg/service"

// RunFileKind is the category of a file saved with a run.
type RunFileKind int64

const (
	RunFileKindOther = RunFileKind(iota)

	// An internal W&B file.
	RunFileKindWandb

	// An artifact file.
	RunFileKindArtifact

	// A media file.
	RunFileKindMedia
)

// RunFileKindFromProto converts the FilesItem.FileType enum to RunFileKind.
func RunFileKindFromProto(enum service.FilesItem_FileType) RunFileKind {
	switch enum {
	case service.FilesItem_WANDB:
		return RunFileKindWandb
	case service.FilesItem_ARTIFACT:
		return RunFileKindArtifact
	case service.FilesItem_MEDIA:
		return RunFileKindMedia
	default:
		return RunFileKindOther
	}
}
