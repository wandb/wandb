package server

import (
	"fmt"
	"path/filepath"

	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/proto"
)

type FilesHandlerOption func(*FilesHandler)

func WithFilterFn(fn func(*service.FilesItem) bool) FilesHandlerOption {
	return func(fh *FilesHandler) {
		fh.filterFn = fn
	}
}

func WithLiveFn(fn func(map[string]struct{})) FilesHandlerOption {
	return func(fh *FilesHandler) {
		fh.liveSet.fn = fn
	}
}

func WithNowFn(fn func(map[string]struct{})) FilesHandlerOption {
	return func(fh *FilesHandler) {
		fh.nowSet.fn = fn
	}
}

func WithEndFn(fn func(map[string]struct{})) FilesHandlerOption {
	return func(fh *FilesHandler) {
		fh.endSet.fn = fn
	}
}

func WithLogger(logger *observability.CoreLogger) FilesHandlerOption {
	return func(fh *FilesHandler) {
		fh.logger = logger
	}
}

type FilesSet struct {
	set map[string]struct{}
	fn  func(map[string]struct{})
}

func NewFilesSet() *FilesSet {
	return &FilesSet{
		set: make(map[string]struct{}),
		fn:  func(map[string]struct{}) {},
	}
}

func (fs *FilesSet) Add(file *service.FilesItem) {
	if _, ok := fs.set[file.Path]; !ok {
		fs.set[file.Path] = struct{}{}
	}
}

func (fs *FilesSet) Flush() {
	if len(fs.set) == 0 {
		return
	}
	fs.fn(fs.set)
	clear(fs.set)
}

type FilesHandler struct {
	endSet   *FilesSet
	nowSet   *FilesSet
	liveSet  *FilesSet
	filterFn func(*service.FilesItem) bool
	logger   *observability.CoreLogger
}

func NewFilesHandler(opts ...FilesHandlerOption) *FilesHandler {
	fh := &FilesHandler{
		endSet:  NewFilesSet(),
		nowSet:  NewFilesSet(),
		liveSet: NewFilesSet(),
		filterFn: func(*service.FilesItem) bool {
			return false
		},
	}
	for _, opt := range opts {
		opt(fh)
	}
	return fh
}

func (fh *FilesHandler) globs(globs []*service.FilesItem) []*service.FilesItem {
	var files []*service.FilesItem
	for _, glob := range globs {
		matches, err := filepath.Glob(glob.Path)
		if len(matches) == 0 {
			files = append(files, glob)
			continue
		}
		if err != nil {
			fh.logger.CaptureError("error matching glob", err, "glob", glob.Path)
			continue
		}
		for _, match := range matches {
			file := proto.Clone(glob).(*service.FilesItem)
			file.Path = match
			files = append(files, file)
		}
	}
	return files
}

func (fh *FilesHandler) Handle(record *service.Record) error {
	files := fh.globs(record.GetFiles().GetFiles())
	if err := fh.add(files); err != nil {
		return err
	}
	fh.nowSet.Flush()
	fh.liveSet.Flush()
	return nil
}

func (fh *FilesHandler) Flush() error {
	fh.endSet.Flush()
	return nil
}

func (fh *FilesHandler) add(files []*service.FilesItem) error {
	for _, file := range files {
		if fh.filterFn(file) {
			continue
		}
		switch file.Policy {
		case service.FilesItem_NOW:
			fh.nowSet.Add(file)
		case service.FilesItem_END:
			fh.endSet.Add(file)
		case service.FilesItem_LIVE:
			fh.liveSet.Add(file)
			fh.endSet.Add(file)
		default:
			err := fmt.Errorf("unknown policy: %s", file.Policy)
			fh.logger.CaptureError("unknown policy", err, "policy", file.Policy)
			continue
		}
	}
	return nil
}
