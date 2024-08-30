package filetransfer

import spb "github.com/wandb/wandb/core/pkg/service_go_proto"

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
func RunFileKindFromProto(enum spb.FilesItem_FileType) RunFileKind {
	switch enum {
	case spb.FilesItem_WANDB:
		return RunFileKindWandb
	case spb.FilesItem_ARTIFACT:
		return RunFileKindArtifact
	case spb.FilesItem_MEDIA:
		return RunFileKindMedia
	default:
		return RunFileKindOther
	}
}
