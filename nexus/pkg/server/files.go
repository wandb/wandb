package server

import (
	"github.com/wandb/wandb/nexus/internal/watcher"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/proto"
)

type FileHandler struct {
	savedFiles map[string]interface{}
	final      *service.Record
	watcher    *watcher.Watcher
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

	var files []*service.FilesItem
	for _, item := range record.GetFiles().GetFiles() {
		// TODO: support live policy?
		if item.Policy == service.FilesItem_END || item.Policy == service.FilesItem_LIVE {
			// todo: handle globs in path
			if _, ok := fh.savedFiles[item.Path]; !ok {
				fh.savedFiles[item.Path] = nil
				fh.final.GetFiles().Files = append(fh.final.GetFiles().Files, item)
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

func NewFileHandler() *FileHandler {
	fh := &FileHandler{
		savedFiles: make(map[string]interface{}),
		watcher:    watcher.NewWatcher(),
	}
	fh.watcher.Start()
	return fh
}
