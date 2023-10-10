package watcher

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sync"
	"time"

	fw "github.com/radovskyb/watcher"
	"github.com/wandb/wandb/nexus/pkg/service"
)

type Watcher struct {
	watcher *fw.Watcher
	outChan chan *service.FilesRecord
	wg      sync.WaitGroup
	// logger    observability.NexusLogger
}

func NewWatcher() *Watcher {
	return &Watcher{
		watcher: fw.New(),
		outChan: make(chan *service.FilesRecord),
		wg:      sync.WaitGroup{},
		// logger:    logger,
	}
}

func (w *Watcher) Start() {
	w.wg.Add(1)
	go func() {
		fmt.Println("STARTING WATCHER")
	loop:
		for {
			select {
			case event := <-w.watcher.Event:
				fmt.Println(event) // Print the event's info.
				if event.Op == fw.Create || event.Op == fw.Write {
					w.outChan <- &service.FilesRecord{}
				}
			case err := <-w.watcher.Error:
				fmt.Println("ERROR", err)
				fmt.Println(w.watcher.WatchedFiles())
			case <-w.watcher.Closed:
				// w.wg.Done()
				// return
				break loop
			}
		}
		w.wg.Done()
	}()

	// Start the watching process - it'll check for changes every 100ms.
	go func() {
		if err := w.watcher.Start(time.Millisecond * 100); err != nil {
			fmt.Println("ERROR", err)
		}
	}()
	w.watcher.Wait()
	fmt.Println("STARTED WATCHER")
}

func (w *Watcher) Close() {
	w.watcher.Closed <- struct{}{}
	w.wg.Wait()
}

type EventFileInfo struct {
	fs.FileInfo
	name string
}

func (e *EventFileInfo) Name() string {
	return e.name
}

func (w *Watcher) Add(item *service.FilesItem) error {
	matches, err := filepath.Glob(item.Path)
	if err != nil {
		// todo: log error
		return err
	}

	for _, match := range matches {
		fileInfo, err := os.Stat(match)
		if err != nil {
			continue
		}
		if !fileInfo.IsDir() {
			err := w.watcher.Add(match)
			if err != nil {
				// todo: log error
				fmt.Println("ERROR", err)
			}
			e := &EventFileInfo{FileInfo: fileInfo, name: match}
			w.watcher.TriggerEvent(fw.Create, e)
		} else {
			err := w.watcher.AddRecursive(match)
			if err != nil {
				// todo: log error
				continue
			}
		}
	}

	return nil
}
