package watcher

import (
	"io/fs"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/wandb/wandb/nexus/pkg/observability"

	fw "github.com/radovskyb/watcher"
	"github.com/wandb/wandb/nexus/pkg/service"
)

type Watcher struct {
	watcher *fw.Watcher
	pathMap map[string]string
	outChan chan *service.Record
	wg      *sync.WaitGroup
	logger  *observability.NexusLogger
}

func NewWatcher(logger *observability.NexusLogger, outChan chan *service.Record) *Watcher {
	return &Watcher{
		watcher: fw.New(),
		pathMap: make(map[string]string),
		outChan: outChan,
		wg:      &sync.WaitGroup{},
		logger:  logger,
	}
}

func (w *Watcher) Start() {
	w.wg.Add(1)
	go func() {
		w.logger.Debug("starting watcher")
	loop:
		for {
			select {
			case event := <-w.watcher.Event:
				if event.Op == fw.Create || event.Op == fw.Write {
					path := event.Path
					if path == "-" {
						path = event.Name()
						absolutePath, err := filepath.Abs(path)
						if _, ok := w.pathMap[absolutePath]; !ok {
							w.pathMap[absolutePath] = path
						}
						if err != nil {
							w.logger.CaptureError("error getting absolute path", err, "path", path)
							continue
						}
						path = absolutePath
					}

					rec := &service.Record{
						RecordType: &service.Record_Files{
							Files: &service.FilesRecord{
								Files: []*service.FilesItem{},
							},
						},
					}
					rec.GetFiles().Files = append(
						rec.GetFiles().Files,
						&service.FilesItem{
							Policy: service.FilesItem_NOW,
							Path:   w.pathMap[path],
						},
					)
					w.outChan <- rec
				}
			case err := <-w.watcher.Error:
				w.logger.Error("error watching file", "err", err)
			case <-w.watcher.Closed:
				break loop
			}
		}
		w.wg.Done()
	}()

	// Start the watching process - it'll check for changes every 100ms.
	go func() {
		if err := w.watcher.Start(time.Millisecond * 100); err != nil {
			w.logger.Error("error starting watcher", "err", err)
		}
	}()
	w.watcher.Wait()
	w.logger.Debug("watcher started")
}

func (w *Watcher) Close() {
	w.watcher.Close()
	w.wg.Wait()
	w.logger.Debug("watcher closed")
}

type EventFileInfo struct {
	fs.FileInfo
	name string
}

func (e *EventFileInfo) Name() string {
	return e.name
}

func (w *Watcher) Add(path string) error {
	fileInfo, err := os.Stat(path)
	if err != nil {
		return err
	}
	if !fileInfo.IsDir() {
		err := w.watcher.Add(path)
		if err != nil {
			return err
		}
		e := &EventFileInfo{FileInfo: fileInfo, name: path}
		w.watcher.TriggerEvent(fw.Create, e)
	} else {
		err := w.watcher.AddRecursive(path)
		if err != nil {
			return err
		}
	}
	return nil
}
