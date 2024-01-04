package server

import (
	"fmt"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/proto"
)

func makeRecord(fileSet map[string]*service.FilesItem) *service.Record {
	if len(fileSet) == 0 {
		return nil
	}
	files := make([]*service.FilesItem, 0, len(fileSet))
	for _, file := range fileSet {
		file.Policy = service.FilesItem_NOW
		files = append(files, file)
	}
	record := &service.Record{
		RecordType: &service.Record_Files{
			Files: &service.FilesRecord{
				Files: files,
			},
		},
	}
	return record
}

type FilesHandlerOption func(*FilesHandler)

func WithFilesHandlerHandleFn(fn func(*service.Record)) FilesHandlerOption {
	return func(fh *FilesHandler) {
		fh.handleFn = fn
	}
}

func WithFilesHandlerFilterPattern(patterns []string) FilesHandlerOption {
	return func(fh *FilesHandler) {
		fh.filterPattern = patterns
	}
}

type FilesHandler struct {
	endSet        map[string]*service.FilesItem
	logger        *observability.CoreLogger
	watcher       *watcher.Watcher
	handleFn      func(*service.Record)
	filterPattern []string
}

func NewFilesHandler(watcher *watcher.Watcher, logger *observability.CoreLogger) *FilesHandler {
	fh := &FilesHandler{
		endSet:  make(map[string]*service.FilesItem),
		logger:  logger,
		watcher: watcher,
	}
	return fh
}

func (fh *FilesHandler) With(opts ...FilesHandlerOption) *FilesHandler {
	for _, opt := range opts {
		opt(fh)
	}
	return fh
}

// globs expands globs in the given list of files and returns the expanded list.
func (fh *FilesHandler) globs(globs []*service.FilesItem) []*service.FilesItem {
	var files []*service.FilesItem
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
				file := proto.Clone(glob).(*service.FilesItem)
				file.Path = match
				files = append(files, file)
			}
		}
	}
	return files
}

func (fh *FilesHandler) filterFn(file *service.FilesItem) bool {
	if fh.filterPattern == nil {
		return false
	}

	// if _, err := os.Stat(file.Path); err != nil {
	// 	return true
	// }

	for _, pattern := range fh.filterPattern {
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
func (fh *FilesHandler) Handle(record *service.Record) {
	files := fh.globs(record.GetFiles().GetFiles())
	nowSet := make(map[string]*service.FilesItem)
	for _, file := range files {
		switch file.Policy {
		case service.FilesItem_NOW:
			nowSet[file.Path] = file
		case service.FilesItem_END:
			fh.endSet[file.Path] = file
		case service.FilesItem_LIVE:
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

func (fh *FilesHandler) handleLive(file *service.FilesItem) {
	record := makeRecord(map[string]*service.FilesItem{file.Path: file})
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

func (fh *FilesHandler) handleNow(files map[string]*service.FilesItem) {
	record := makeRecord(files)
	if record != nil {
		fh.handleFn(record)
		clear(files)
	}
}

func (fh *FilesHandler) handleEnd() {
	record := makeRecord(fh.endSet)
	if record != nil {
		fh.handleFn(record)
		clear(fh.endSet)
	}
}

func (fh *FilesHandler) Flush() {
	fh.handleEnd()
}

func (fh *FilesHandler) Close() {
	if fh == nil {
		return
	}
	fh.watcher.Close()
	fh.logger.Debug("closed file handler")
}
