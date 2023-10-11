package watcher

import (
	"fmt"
	"io/fs"
	"os"
	"sync"
	"time"

	fw "github.com/radovskyb/watcher"
	"github.com/wandb/wandb/nexus/pkg/service"
)

type Watcher struct {
	watcher *fw.Watcher
	outChan chan *service.Record
	wg      *sync.WaitGroup
	// logger    observability.NexusLogger
}

func NewWatcher(outChan chan *service.Record) *Watcher {
	return &Watcher{
		watcher: fw.New(),
		outChan: outChan,
		wg:      &sync.WaitGroup{},
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
					path := event.Path
					if path == "-" {
						path = event.Name()
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
							Path:   path,
						},
					)
					fmt.Println(rec)
					w.outChan <- rec
					fmt.Println("LOL")
				}
			case err := <-w.watcher.Error:
				fmt.Println("ERROR", err)
				fmt.Println(w.watcher.WatchedFiles())
			case <-w.watcher.Closed:
				fmt.Println("DONE")
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
		fmt.Println("DONE STARTING WATCHER")
	}()
	w.watcher.Wait()
	fmt.Println("STARTED WATCHER")
}

func (w *Watcher) Close() {
	fmt.Println("STARTING CLOSING WATCHER")
	w.watcher.Close()
	fmt.Println("CANCELLED WATCHER")
	w.wg.Wait()
	fmt.Println("CLOSED WATCHER")
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
