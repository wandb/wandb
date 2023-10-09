package watcher

import (
	"fmt"
	fw "github.com/radovskyb/watcher"
	"github.com/wandb/wandb/nexus/pkg/service"
	"log"
	"sync"
	"time"
)

type Watcher struct {
	watcher   *fw.Watcher
	outChan   chan *service.FilesRecord
	watchlist map[string]*service.FilesItem
	wg        sync.WaitGroup
	// logger    observability.NexusLogger
}

func NewWatcher() *Watcher {
	return &Watcher{
		watcher:   fw.New(),
		outChan:   make(chan *service.FilesRecord),
		watchlist: make(map[string]*service.FilesItem),
		wg:        sync.WaitGroup{},
		// logger:    logger,
	}
}

func (w *Watcher) Start() {
	w.wg.Add(1)
	go func() {
	loop:
		for {
			select {
			case event := <-w.watcher.Event:
				fmt.Println(event) // Print the event's info.
			case err := <-w.watcher.Error:
				log.Fatalln(err)
			case <-w.watcher.Closed:
				// w.wg.Done()
				// return
				break loop
			}
		}
		w.wg.Done()
	}()

	// Start the watching process - it'll check for changes every 100ms.
	if err := w.watcher.Start(time.Millisecond * 100); err != nil {
		log.Fatalln(err)
	}
	w.watcher.Wait()
}

func (w *Watcher) Close() {
	w.watcher.Closed <- struct{}{}
	w.wg.Wait()
}

func (w *Watcher) Add(item *service.FilesItem) error {
	err := w.watcher.Add(item.Path)
	if err != nil {
		fmt.Println("ERROR", err)
	}
	return err
}

// func (w *Watcher) Add(item *service.FilesItem) error {
// 	w.watchlist[item.Path] = item
// 	return w.watcher.Add(item.Path)
// }
//
// func (w *Watcher) Close() error {
// 	return w.watcher.Close()
// }
