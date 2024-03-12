package runfiles

import "github.com/wandb/wandb/core/pkg/service"

// Metadata about a file that's not its path.
type FileInfo struct {
	Type service.FilesItem_FileType
}
