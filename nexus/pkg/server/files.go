package server

import (
	"fmt"
	"github.com/wandb/wandb/nexus/internal/watcher"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/proto"
	"path/filepath"
)

type FileHandler struct {
	savedFiles map[string]interface{}
	final      *service.Record
	watcher    *watcher.Watcher
}

func NewFileHandler(watcherOutChan chan *service.Record) *FileHandler {
	return &FileHandler{
		savedFiles: make(map[string]interface{}),
		watcher:    watcher.NewWatcher(watcherOutChan),
	}
}

func (fh *FileHandler) Start() {
	fh.watcher.Start()
}

func (fh *FileHandler) Close() {
	if fh == nil {
		return
	}
	fh.watcher.Close()
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
			// todo: log error
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

	fmt.Println("ITEMS", items)

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
				// todo: log error
				continue
			}
		} else {
			files = append(files, item)
		}
	}

	if files == nil {
		return nil
	}

	// TODO: should we replace clone with something else?
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
