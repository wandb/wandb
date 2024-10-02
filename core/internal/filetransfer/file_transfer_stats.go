package filetransfer

import (
	"sync"
	"sync/atomic"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// FileTransferStats reports file upload/download progress and totals.
type FileTransferStats interface {
	// GetFilesStats returns byte counts for uploads.
	GetFilesStats() *spb.FilePusherStats

	// GetFileCounts returns a breakdown of the kinds of files uploaded.
	GetFileCounts() *spb.FileCounts

	// IsDone returns whether all uploads finished.
	IsDone() bool

	// SetDone marks all uploads as finished.
	SetDone()

	// UpdateUploadStats updates the upload stats for a file.
	UpdateUploadStats(newInfo FileUploadInfo)
}

type fileTransferStats struct {
	sync.Mutex

	done *atomic.Bool

	statsByPath map[string]FileUploadInfo

	uploadedBytes *atomic.Int64
	totalBytes    *atomic.Int64
	dedupedBytes  *atomic.Int64

	wandbCount    *atomic.Int32
	mediaCount    *atomic.Int32
	artifactCount *atomic.Int32
	otherCount    *atomic.Int32
}

func NewFileTransferStats() FileTransferStats {
	return &fileTransferStats{
		done: &atomic.Bool{},

		statsByPath: make(map[string]FileUploadInfo),

		uploadedBytes: &atomic.Int64{},
		totalBytes:    &atomic.Int64{},
		dedupedBytes:  &atomic.Int64{},

		wandbCount:    &atomic.Int32{},
		mediaCount:    &atomic.Int32{},
		artifactCount: &atomic.Int32{},
		otherCount:    &atomic.Int32{},
	}
}

func (fts *fileTransferStats) GetFilesStats() *spb.FilePusherStats {
	// NOTE: We don't lock, so these could be out of sync. For instance,
	// TotalBytes could be less than UploadedBytes!
	return &spb.FilePusherStats{
		UploadedBytes: fts.uploadedBytes.Load(),
		TotalBytes:    fts.totalBytes.Load(),
		DedupedBytes:  fts.dedupedBytes.Load(),
	}
}

func (fts *fileTransferStats) GetFileCounts() *spb.FileCounts {
	return &spb.FileCounts{
		WandbCount:    fts.wandbCount.Load(),
		MediaCount:    fts.mediaCount.Load(),
		ArtifactCount: fts.artifactCount.Load(),
		OtherCount:    fts.otherCount.Load(),
	}
}

func (fts *fileTransferStats) IsDone() bool {
	return fts.done.Load()
}

func (fts *fileTransferStats) SetDone() {
	fts.done.Store(true)
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
	fts.uploadedBytes.Add(info.UploadedBytes * mult)
	fts.totalBytes.Add(info.TotalBytes * mult)

	switch info.FileKind {
	default:
		fts.otherCount.Add(int32(mult))
	case RunFileKindWandb:
		fts.wandbCount.Add(int32(mult))
	case RunFileKindArtifact:
		fts.artifactCount.Add(int32(mult))
	case RunFileKindMedia:
		fts.mediaCount.Add(int32(mult))
	}
}
