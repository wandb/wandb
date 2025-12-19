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

	// UpdateDownloadStats updates the download stats for a file.
	UpdateDownloadStats(newInfo FileDownloadInfo)
}

type fileTransferStats struct {
	sync.Mutex

	done *atomic.Bool

	uploadStatsByPath map[string]FileUploadInfo

	uploadedBytes *atomic.Int64
	totalBytes    *atomic.Int64

	downloadStatsByPath  map[string]FileDownloadInfo
	downloadedBytes      *atomic.Int64
	totalDownloadedBytes *atomic.Int64

	wandbCount    *atomic.Int32
	mediaCount    *atomic.Int32
	artifactCount *atomic.Int32
	otherCount    *atomic.Int32
}

func NewFileTransferStats() FileTransferStats {
	return &fileTransferStats{
		done: &atomic.Bool{},

		uploadStatsByPath: make(map[string]FileUploadInfo),

		uploadedBytes: &atomic.Int64{},
		totalBytes:    &atomic.Int64{},

		downloadStatsByPath:  make(map[string]FileDownloadInfo),
		downloadedBytes:      &atomic.Int64{},
		totalDownloadedBytes: &atomic.Int64{},

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

type FileDownloadInfo struct {
	// The local path to the file being downloaded.
	Path string

	// The number of bytes downloaded so far.
	DownloadedBytes int64

	// The total number of bytes being downloaded.
	TotalBytes int64
}

func (fts *fileTransferStats) UpdateUploadStats(newInfo FileUploadInfo) {
	fts.Lock()
	defer fts.Unlock()

	if oldInfo, ok := fts.uploadStatsByPath[newInfo.Path]; ok {
		fts.addStats(oldInfo, -1)
	}

	fts.uploadStatsByPath[newInfo.Path] = newInfo
	fts.addStats(newInfo, 1)
}

func (fts *fileTransferStats) UpdateDownloadStats(newInfo FileDownloadInfo) {
	fts.Lock()
	defer fts.Unlock()

	if oldInfo, ok := fts.downloadStatsByPath[newInfo.Path]; ok {
		fts.downloadedBytes.Add(-oldInfo.DownloadedBytes)
		fts.totalDownloadedBytes.Add(-oldInfo.TotalBytes)
	}

	fts.downloadStatsByPath[newInfo.Path] = newInfo
	fts.downloadedBytes.Add(newInfo.DownloadedBytes)
	fts.totalDownloadedBytes.Add(newInfo.TotalBytes)
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
