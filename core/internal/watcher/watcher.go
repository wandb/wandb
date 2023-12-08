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

const pollingInterval = time.Millisecond * 100

type Watcher struct {
	watcher *fw.Watcher
	pathMap map[string]string
	outChan chan *service.Record
	wg      *sync.WaitGroup
	logger  *observability.CoreLogger
}

func NewWatcher(logger *observability.CoreLogger, outChan chan *service.Record) *Watcher {
	return &Watcher{
		watcher: fw.New(),
		pathMap: make(map[string]string),
		outChan: outChan,
		wg:      &sync.WaitGroup{},
		logger:  logger,
	}
}

// Start starts the watcher and forwards upload requests
// when watched files are created or written to.
func (w *Watcher) Start() {
	w.wg.Add(1)
	go func() {
		w.logger.Debug("starting watcher")
	loop:
		for {
			select {
			case event := <-w.watcher.Event:
				// Only trigger on create and write events.
				// The record we send on the channel must contain the relative path
				// to comply with the backend's expectations
				if event.Op == fw.Create || event.Op == fw.Write {
					path := event.Path
					// The first time we see a file, it comes from a manual trigger
					// where event.Path is not defined. We compute the absolute path
					// and store a map of absolute path to the user-provided relative path.
					// On subsequent events, we use the map to get the relative path.
					if path == "-" {
						path = event.Name()
						absolutePath, err := filepath.Abs(path)
						if err != nil {
							w.logger.CaptureError("error getting absolute path", err, "path", path)
							continue
						}
						if _, ok := w.pathMap[absolutePath]; !ok {
							w.pathMap[absolutePath] = path
						}
						path = absolutePath
					}
					// skip directories and files that don't exist
					if fileInfo, err := os.Stat(path); err != nil || fileInfo.IsDir() {
						continue
					}

					// at this point, we know that the file needs to be uploaded,
					// so we send a Files record on the channel with the NOW policy
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

	// Start the watching process - it'll check for changes every pollingInterval ms.
	go func() {
		if err := w.watcher.Start(pollingInterval); err != nil {
			w.logger.Error("error starting watcher", "err", err)
		}
	}()
	w.watcher.Wait()
	w.logger.Debug("watcher started")
}

// Close closes the watcher
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

// Add adds a path to the watcher's watch list
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
		// w.watcher.Add() doesn't trigger an event for an existing file, so we do it manually
		e := &EventFileInfo{FileInfo: fileInfo, name: path}
		w.watcher.TriggerEvent(fw.Create, e)
	} else {
		// w.watcher.AddRecursive() does trigger events for existing files
		err := w.watcher.AddRecursive(path)
		if err != nil {
			return err
		}
	}
	return nil
}
