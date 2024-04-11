package filetransfer

import (
	"sync"

	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/proto"
)

// FileTransferStats reports file upload/download progress and totals.
type FileTransferStats interface {
	// GetFilesStats returns byte counts for uploads.
	GetFilesStats() *service.FilePusherStats

	// GetFileCounts returns a breakdown of the kinds of files uploaded.
	GetFileCounts() *service.FileCounts

	// IsDone returns whether all uploads finished.
	IsDone() bool

	// SetDone marks all uploads as finished.
	SetDone()

	// UpdateUploadStats updates the tr
	UpdateUploadStats(newInfo FileUploadInfo)
}

type fileTransferStats struct {
	*sync.Mutex

	done bool

	statsByPath map[string]FileUploadInfo
	filesStats  *service.FilePusherStats
	fileCounts  *service.FileCounts
}

func NewFileTransferStats() FileTransferStats {
	return &fileTransferStats{
		Mutex:       &sync.Mutex{},
		statsByPath: make(map[string]FileUploadInfo),
		filesStats:  &service.FilePusherStats{},
		fileCounts:  &service.FileCounts{},
	}
}

func (fts *fileTransferStats) GetFilesStats() *service.FilePusherStats {
	return proto.Clone(fts.filesStats).(*service.FilePusherStats)
}

func (fts *fileTransferStats) GetFileCounts() *service.FileCounts {
	return proto.Clone(fts.fileCounts).(*service.FileCounts)
}

func (fts *fileTransferStats) IsDone() bool {
	return fts.done
}

func (fts *fileTransferStats) SetDone() {
	fts.done = true
}

// FileUploadInfo is information about an in-progress file upload.
type FileUploadInfo struct {
	// The local path to the file being uploaded.
	Path string

	// The kind of file this is.
	FileKind RunFileKind

	// The number of bytes uploaded so far.
	UploadedBytes int64

	// The total number of bytes being uploaded.
	TotalBytes int64
}

func (fts *fileTransferStats) UpdateUploadStats(newInfo FileUploadInfo) {
	fts.Lock()
	defer fts.Unlock()

	if oldInfo, ok := fts.statsByPath[newInfo.Path]; ok {
		fts.addStats(oldInfo, -1)
	}

	fts.statsByPath[newInfo.Path] = newInfo
	fts.addStats(newInfo, 1)
}

func (fts *fileTransferStats) addStats(info FileUploadInfo, mult int64) {
	fts.filesStats.UploadedBytes += info.UploadedBytes * mult
	fts.filesStats.TotalBytes += info.TotalBytes * mult

	switch info.FileKind {
	default:
		fts.fileCounts.OtherCount += int32(mult)
	case RunFileKindWandb:
		fts.fileCounts.WandbCount += int32(mult)
	case RunFileKindArtifact:
		fts.fileCounts.ArtifactCount += int32(mult)
	case RunFileKindMedia:
		fts.fileCounts.MediaCount += int32(mult)
	}
}
