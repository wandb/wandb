package filetransfer

import "github.com/wandb/wandb/core/pkg/service"

// FileTransferStats reports file upload/download progress and totals.
type FileTransferStats interface {
	// GetFilesStats returns byte counts for uploads.
	GetFilesStats() *service.FilePusherStats

	// GetFileCounts returns a breakdown of the kinds of files uploaded.
	GetFileCounts() *service.FileCounts

	// IsDone returns whether all uploads finished.
	IsDone() bool

	// UpdateUploadStats updates the tr
	UpdateUploadStats(newInfo FileUploadInfo)
}

type fileTransferStats struct {
	statsByPath map[string]FileUploadInfo
	filesStats  *service.FilePusherStats
	fileCounts  *service.FileCounts
}

func NewFileTransferStats() FileTransferStats {
	return &fileTransferStats{
		statsByPath: make(map[string]FileUploadInfo),
		filesStats:  &service.FilePusherStats{},
		fileCounts:  &service.FileCounts{},
	}
}

func (fts *fileTransferStats) GetFilesStats() *service.FilePusherStats {
	return fts.filesStats
}

func (fts *fileTransferStats) GetFileCounts() *service.FileCounts {
	return fts.fileCounts
}

func (fts *fileTransferStats) IsDone() bool {
	return fts.filesStats.TotalBytes == fts.filesStats.UploadedBytes
}

// FileUploadInfo is information about an in-progress file upload.
type FileUploadInfo struct {
	// The local path to the file being uploaded.
	Path string

	// The kind of file this is.
	FileKind RunFileKind

	// The number of bytes uploaded so far.
	UploadedBytes int64

	// The total number of bytes of the fully uploaded files.
	TotalBytes int64
}

func (fts *fileTransferStats) UpdateUploadStats(newInfo FileUploadInfo) {
	if oldInfo, ok := fts.statsByPath[newInfo.Path]; ok {
		fts.addStats(oldInfo, -1)
	}

	fts.statsByPath[newInfo.Path] = newInfo
	fts.addStats(newInfo, 1)
}

func (fts *fileTransferStats) addStats(info FileUploadInfo, mult int64) {
	fts.filesStats.UploadedBytes += info.UploadedBytes * mult

	if info.UploadedBytes == info.TotalBytes {
		fts.filesStats.TotalBytes += info.TotalBytes * mult
	}

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
