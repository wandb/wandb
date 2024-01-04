package server

import (
	"fmt"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/proto"
)

type FilesHandler struct {
	nowSet        map[string]struct{}
	endSet        map[string]struct{}
	logger        *observability.CoreLogger
	watcher       *watcher.Watcher
	handleFn      func(*service.Record)
	filterPattern []string
}

func NewFilesHandler(watcher *watcher.Watcher, logger *observability.CoreLogger) *FilesHandler {
	fh := &FilesHandler{
		nowSet:  make(map[string]struct{}),
		endSet:  make(map[string]struct{}),
		logger:  logger,
		watcher: watcher,
	}
	return fh
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

func (fh *FilesHandler) With(opts ...FilesHandlerOption) *FilesHandler {
	for _, opt := range opts {
		opt(fh)
	}
	return fh
}

func (fh *FilesHandler) globs(globs []*service.FilesItem) []*service.FilesItem {
	var files []*service.FilesItem
	for _, glob := range globs {
		if glob.Path == "" {
			continue
		}
		matches, err := filepath.Glob(glob.Path)
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

func (fh *FilesHandler) Handle(record *service.Record) {
	files := fh.globs(record.GetFiles().GetFiles())
	for _, file := range files {
		switch file.Policy {
		case service.FilesItem_NOW:
			fh.nowSet[file.Path] = struct{}{}
		case service.FilesItem_END:
			fh.endSet[file.Path] = struct{}{}
		case service.FilesItem_LIVE:
			fh.endSet[file.Path] = struct{}{}
			fh.handleLive(file.Path)
		default:
			err := fmt.Errorf("unknown policy: %s", file.Policy)
			fh.logger.CaptureError("unknown policy", err, "policy", file.Policy)
			continue
		}
	}
	fh.handleNow()
}

func (fh *FilesHandler) makeRecord(paths map[string]struct{}) *service.Record {
	if len(paths) == 0 {
		return nil
	}

	files := make([]*service.FilesItem, 0, len(paths))
	for path := range paths {
		files = append(files, &service.FilesItem{
			Policy: service.FilesItem_NOW,
			Path:   path,
		})
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

func (fh *FilesHandler) handleLive(path string) {
	record := fh.makeRecord(map[string]struct{}{path: {}})
	fh.watcher.Add(path, func(event watcher.Event) error {
		if event.IsCreate() || event.IsWrite() {
			fh.handleFn(record)
		}
		return nil
	})
}

func (fh *FilesHandler) handleNow() {
	record := fh.makeRecord(fh.nowSet)
	if record != nil {
		fh.handleFn(record)
		clear(fh.nowSet)
	}
}

func (fh *FilesHandler) handleEnd() {
	record := fh.makeRecord(fh.endSet)
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
