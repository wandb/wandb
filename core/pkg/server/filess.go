package server

import (
	"fmt"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/proto"
)

// type FilesSet struct {
// 	set map[string]struct{}
// 	fn  func(map[string]struct{})
// }

// func NewFilesSet() *FilesSet {
// 	return &FilesSet{
// 		set: make(map[string]struct{}),
// 		fn:  func(map[string]struct{}) {},
// 	}
// }

// func (fs *FilesSet) Add(file *service.FilesItem) {
// 	if _, ok := fs.set[file.Path]; !ok {
// 		fs.set[file.Path] = struct{}{}
// 	}
// }

// func (fs *FilesSet) Set() map[string]struct{} {
// 	return fs.set
// }

// func (fs *FilesSet) Flush() {
// 	if len(fs.set) == 0 {
// 		return
// 	}
// 	fs.fn(fs.set)
// 	clear(fs.set)
// }

// type FilesHandlerOption func(*FilesHandler)

// func WithFilesHandlerFilterFn(fn func(*service.FilesItem) bool) FilesHandlerOption {
// 	return func(fh *FilesHandler) {
// 		fh.filterFn = fn
// 	}
// }

// func WithFilesHandlerLiveFn(fn func(map[string]struct{})) FilesHandlerOption {
// 	return func(fh *FilesHandler) {
// 		fh.liveSet.fn = fn
// 	}
// }

// func WithFilesHandlerNowFn(fn func(map[string]struct{})) FilesHandlerOption {
// 	return func(fh *FilesHandler) {
// 		fh.nowSet.fn = fn
// 	}
// }

// func WithEndFn(fn func(map[string]struct{})) FilesHandlerOption {
// 	return func(fh *FilesHandler) {
// 		fh.endSet.fn = fn
// 	}
// }

// func WithLogger(logger *observability.CoreLogger) FilesHandlerOption {
// 	return func(fh *FilesHandler) {
// 		fh.logger = logger
// 	}
// }

type FilesHandler struct {
	nowSet   map[string]struct{}
	endSet   map[string]struct{}
	watcher  *watcher.Watcher
	outChan  chan *service.Record
	filterFn func(*service.FilesItem) bool
	logger   *observability.CoreLogger
}

func NewFilesHandler(logger *observability.CoreLogger) *FilesHandler {
	fh := &FilesHandler{
		// endSet:  NewFilesSet(),
		// nowSet:  NewFilesSet(),
		// liveSet: NewFilesSet(),
		nowSet:  make(map[string]struct{}),
		endSet:  make(map[string]struct{}),
		watcher: watcher.New(),
		outChan: make(chan *service.Record, BufferSize),
		filterFn: func(*service.FilesItem) bool {
			return false
		},
		logger: logger,
	}
	return fh
}

// func (fh *FilesHandler) Start(opts ...FilesHandlerOption) {
// 	for _, opt := range opts {
// 		opt(fh)
// 	}
// }

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
	// 	fh.nowSet.Flush()
	// 	fh.liveSet.Flush()
	return nil
}

// func (fh *FilesHandler) Flush() error {
// 	fh.endSet.Flush()
// 	return nil
// }

func (fh *FilesHandler) add(files []*service.FilesItem) error {
	for _, file := range files {
		if fh.filterFn(file) {
			continue
		}
		switch file.Policy {
		case service.FilesItem_NOW:
			fh.addNow(file)
		case service.FilesItem_END:
			fh.addEnd(file)
		case service.FilesItem_LIVE:
			fh.addLive(file)
		default:
			err := fmt.Errorf("unknown policy: %s", file.Policy)
			fh.logger.CaptureError("unknown policy", err, "policy", file.Policy)
			continue
		}
	}
	return nil
}

func (fh *FilesHandler) addNow(file *service.FilesItem) {

	rec := &service.Record{
		RecordType: &service.Record_Files{
			Files: &service.FilesRecord{
				Files: []*service.FilesItem{
					{
						Policy: service.FilesItem_NOW,
						Path:   file.Path,
					},
				},
			},
		},
	}
	fh.outChan <- rec
}

func (fh *FilesHandler) addEnd(file *service.FilesItem) {

}

func (fh *FilesHandler) addLive(file *service.FilesItem) {
	fh.watcher.Add(file.Path, func(event watcher.Event) error {
		if event.IsCreate() || event.IsWrite() {
			rec := &service.Record{
				RecordType: &service.Record_Files{
					Files: &service.FilesRecord{
						Files: []*service.FilesItem{
							{
								Policy: service.FilesItem_LIVE,
								Path:   file.Path,
							},
						},
					},
				},
			}
			fh.outChan <- rec
		}
		return nil
	})
}
