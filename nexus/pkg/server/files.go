package server

import (
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

func (fh *FileHandler) Start() {
	fh.logger.Debug("starting file handler")
	fh.watcher.Start()
}

func (fh *FileHandler) Close() {
	if fh == nil {
		return
	}
	fh.watcher.Close()
	fh.logger.Debug("closed file handler")
}

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

		if err != nil {
			fh.logger.CaptureError("error expanding glob", err, "path", item.Path)
			continue
		}

		// if no matches, just add the item assuming it's not a glob
		if len(matches) == 0 {
			items = append(items, item)
			continue
		}

		// expand globs
		for _, match := range matches {
			newItem := proto.Clone(item).(*service.FilesItem)
			newItem.Path = match
			items = append(items, newItem)
		}
	}

	var files []*service.FilesItem
	for _, item := range items {
		if item.Policy == service.FilesItem_END {
			if _, ok := fh.savedFiles[item.Path]; !ok {
				fh.savedFiles[item.Path] = nil
				fh.final.GetFiles().Files = append(fh.final.GetFiles().Files, item)
			}
		} else if item.Policy == service.FilesItem_LIVE {
			if _, ok := fh.savedFiles[item.Path]; !ok {
				fh.savedFiles[item.Path] = nil
				fh.final.GetFiles().Files = append(fh.final.GetFiles().Files, item)
			}
			err := fh.watcher.Add(item.Path)
			if err != nil {
				fh.logger.CaptureError("error adding path to watcher", err, "path", item.Path)
				continue
			}
		} else {
			files = append(files, item)
		}
	}

	if files == nil {
		return nil
	}

	rec := proto.Clone(record).(*service.Record)
	rec.GetFiles().Files = files
	return rec
}

func (fh *FileHandler) Final() *service.Record {
	if fh == nil {
		return nil
	}
	return fh.final
}
