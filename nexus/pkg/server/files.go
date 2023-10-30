package server

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/wandb/wandb/nexus/pkg/observability"

	"github.com/wandb/wandb/nexus/internal/watcher"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/proto"
)

type FileHandler struct {
	savedFiles map[string]interface{}
	final      *service.Record
	watcher    *watcher.Watcher
	logger     *observability.NexusLogger
}

func NewFileHandler(logger *observability.NexusLogger, watcherOutChan chan *service.Record) *FileHandler {
	return &FileHandler{
		savedFiles: make(map[string]interface{}),
		watcher:    watcher.NewWatcher(logger, watcherOutChan),
		logger:     logger,
	}
}

// Start starts the file handler and the watcher
func (fh *FileHandler) Start() {
	fh.logger.Debug("starting file handler")
	fh.watcher.Start()
}

// Close closes the file handler and the watcher
func (fh *FileHandler) Close() {
	if fh == nil {
		return
	}
	fh.watcher.Close()
	fh.logger.Debug("closed file handler")
}

// Handle handles file uploads preprocessing, depending on their policies:
// - NOW: upload immediately
// - END: upload at the end of the run
// - LIVE: upload immediately, on changes, and at the end of the run
func (fh *FileHandler) Handle(record *service.Record) *service.Record {
	if fh.final == nil {
		fh.final = &service.Record{
			RecordType: &service.Record_Files{
				Files: &service.FilesRecord{
					Files: []*service.FilesItem{},
				},
			},
		}
	}

	// expand globs
	var items []*service.FilesItem
	for _, item := range record.GetFiles().GetFiles() {
		matches, err := filepath.Glob(item.Path)

		// if no matches, just add the item assuming it's not a glob
		if len(matches) == 0 {
			// TODO: fix this. if item.Path is a relative path, it will be relative to the current working directory
			// if fileInfo, err := os.Stat(item.Path); err != nil || fileInfo.IsDir() {
			// 	continue
			// }
			items = append(items, item)
			continue
		}

		if err != nil {
			fh.logger.CaptureError("error expanding glob", err, "path", item.Path)
			continue
		}

		// expand globs
		for _, match := range matches {
			if fileInfo, err := os.Stat(match); err != nil || fileInfo.IsDir() {
				continue
			}
			newItem := proto.Clone(item).(*service.FilesItem)
			newItem.Path = match
			items = append(items, newItem)
		}
	}

	var files []*service.FilesItem
	for _, item := range items {
		switch item.Policy {
		case service.FilesItem_NOW:
			files = append(files, item)
		case service.FilesItem_END:
			if _, ok := fh.savedFiles[item.Path]; !ok {
				fh.savedFiles[item.Path] = nil
				fh.final.GetFiles().Files = append(fh.final.GetFiles().Files, item)
			}
		case service.FilesItem_LIVE:
			if _, ok := fh.savedFiles[item.Path]; !ok {
				fh.savedFiles[item.Path] = nil
				fh.final.GetFiles().Files = append(fh.final.GetFiles().Files, item)
			}
			err := fh.watcher.Add(item.Path)
			if err != nil {
				fh.logger.CaptureError("error adding path to watcher", err, "path", item.Path)
				continue
			}
		default:
			err := fmt.Errorf("unknown file policy: %s", item.Policy)
			fh.logger.CaptureError("unknown file policy", err, "policy", item.Policy)
		}
	}

	if files == nil {
		return nil
	}

	rec := proto.Clone(record).(*service.Record)
	rec.GetFiles().Files = files
	return rec
}

// Final returns the stored record to be uploaded at the end of the run (DeferRequest_FLUSH_DIR)
func (fh *FileHandler) Final() *service.Record {
	if fh == nil {
		return nil
	}
	return fh.final
}
