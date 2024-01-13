package handler

import (
	"fmt"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/watcher"
	"google.golang.org/protobuf/proto"

	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

func makeRecord(fileSet map[string]*pb.FilesItem) *pb.Record {
	if len(fileSet) == 0 {
		return nil
	}
	files := make([]*pb.FilesItem, 0, len(fileSet))
	for _, file := range fileSet {
		file.Policy = pb.FilesItem_NOW
		files = append(files, file)
	}
	record := &pb.Record{
		RecordType: &pb.Record_Files{
			Files: &pb.FilesRecord{
				Files: files,
			},
		},
	}
	return record
}

type FilesHandlerOption func(*Files)

func WithFilesHandlerHandleFn(fn func(*pb.Record)) FilesHandlerOption {
	return func(fh *Files) {
		fh.handleFn = fn
	}
}

type Files struct {
	watcher  *watcher.Watcher
	handleFn func(*pb.Record)
	endSet   map[string]*pb.FilesItem
	settings *pb.Settings
	logger   *observability.CoreLogger
}

func NewFiles(watcher *watcher.Watcher, logger *observability.CoreLogger, settings *pb.Settings) *Files {
	fh := &Files{
		endSet:   make(map[string]*pb.FilesItem),
		logger:   logger,
		settings: settings,
		watcher:  watcher,
	}
	return fh
}

func (fh *Files) With(opts ...FilesHandlerOption) *Files {
	for _, opt := range opts {
		opt(fh)
	}
	return fh
}

// globs expands globs in the given list of files and returns the expanded list.
func (fh *Files) globs(globs []*pb.FilesItem) []*pb.FilesItem {
	var files []*pb.FilesItem
	for _, glob := range globs {
		if glob.Path == "" {
			continue
		}
		matches, err := filepath.Glob(glob.Path)
		// if no matches, just add the item assuming it's not a glob
		if len(matches) == 0 {
			if !fh.filterFn(glob) {
				files = append(files, glob)
			}
			continue
		}
		if err != nil {
			fh.logger.CaptureError("error matching glob", err, "glob", glob.Path)
			continue
		}
		for _, match := range matches {
			if !fh.filterFn(glob) {
				file := proto.Clone(glob).(*pb.FilesItem)
				file.Path = match
				files = append(files, file)
			}
		}
	}
	return files
}

func (fh *Files) filterFn(file *pb.FilesItem) bool {
	filterPattern := fh.settings.GetIgnoreGlobs().GetValue()
	if len(filterPattern) == 0 {
		return false
	}

	for _, pattern := range filterPattern {
		if matches, err := filepath.Match(pattern, file.Path); err != nil {
			fh.logger.CaptureError("error matching glob", err, "path", file.Path, "glob", pattern)
			continue
		} else if matches {
			fh.logger.Info("ignoring file", "path", file.Path, "glob", pattern)
			return true
		}
	}
	return false
}

// Handle handles file uploads preprocessing, depending on their policies:
// - NOW: upload immediately
// - END: upload at the end of the run
// - LIVE: upload immediately, on changes, and at the end of the run
func (fh *Files) Handle(record *pb.Record) {
	if fh == nil || fh.handleFn == nil {
		return
	}
	files := fh.globs(record.GetFiles().GetFiles())
	nowSet := make(map[string]*pb.FilesItem)
	for _, file := range files {
		switch file.Policy {
		case pb.FilesItem_NOW:
			nowSet[file.Path] = file
		case pb.FilesItem_END:
			fh.endSet[file.Path] = file
		case pb.FilesItem_LIVE:
			fh.endSet[file.Path] = file
			fh.handleLive(file)
		default:
			err := fmt.Errorf("unknown policy: %s", file.Policy)
			fh.logger.CaptureError("unknown policy", err, "policy", file.Policy)
			continue
		}
	}
	fh.handleNow(nowSet)
}

func (fh *Files) handleLive(file *pb.FilesItem) {
	record := makeRecord(map[string]*pb.FilesItem{file.Path: file})
	if record == nil {
		return
	}
	err := fh.watcher.Add(file.Path, func(event watcher.Event) error {
		if event.IsCreate() || event.IsWrite() {
			fh.handleFn(record)
		}
		return nil
	})
	if err != nil {
		fh.logger.CaptureError("error adding path to watcher", err, "file", file)
	}
}

func (fh *Files) handleNow(files map[string]*pb.FilesItem) {
	record := makeRecord(files)
	if record != nil {
		fh.handleFn(record)
		clear(files)
	}
}

func (fh *Files) handleEnd() {
	record := makeRecord(fh.endSet)
	if record != nil {
		fh.handleFn(record)
		clear(fh.endSet)
	}
}

func (fh *Files) Flush() {
	fh.handleEnd()
}

// FilesInfo is a handler for file transfer info records.
type FilesInfo struct {
	tracked    map[string]*pb.FileTransferInfoRequest
	filesStats *pb.FilePusherStats
	filesCount *pb.FileCounts
}

func NewFilesInfo() *FilesInfo {
	return &FilesInfo{
		filesStats: &pb.FilePusherStats{},
		tracked:    make(map[string]*pb.FileTransferInfoRequest),
		filesCount: &pb.FileCounts{},
	}
}

func (fh *FilesInfo) Handle(record *pb.Record) {
	request := record.GetRequest().GetFileTransferInfo()
	fileCounts := request.GetFileCounts()
	path := request.GetPath()
	if info, ok := fh.tracked[path]; ok {
		fh.filesStats.UploadedBytes += request.GetProcessed() - info.GetProcessed()
		fh.filesCount.OtherCount += fileCounts.GetOtherCount() - info.GetFileCounts().GetOtherCount()
		fh.filesCount.WandbCount += fileCounts.GetWandbCount() - info.GetFileCounts().GetWandbCount()
		fh.filesCount.MediaCount += fileCounts.GetMediaCount() - info.GetFileCounts().GetMediaCount()
		fh.filesCount.ArtifactCount += fileCounts.GetArtifactCount() - info.GetFileCounts().GetArtifactCount()
		fh.tracked[path] = request
	} else {
		fh.filesStats.TotalBytes += request.GetSize()
		fh.filesStats.UploadedBytes += request.GetProcessed()
		fh.filesCount.OtherCount += fileCounts.GetOtherCount()
		fh.filesCount.WandbCount += fileCounts.GetWandbCount()
		fh.filesCount.MediaCount += fileCounts.GetMediaCount()
		fh.filesCount.ArtifactCount += fileCounts.GetArtifactCount()
		fh.tracked[path] = request
	}
}

func (fh *FilesInfo) GetFilesStats() *pb.FilePusherStats {
	return fh.filesStats
}

func (fh *FilesInfo) GetFilesCount() *pb.FileCounts {
	return fh.filesCount
}

func (fh *FilesInfo) GetDone() bool {
	return fh.filesStats.TotalBytes == fh.filesStats.UploadedBytes
}
