package watcher

import (
	"fmt"
	"github.com/wandb/wandb/nexus/pkg/service"

	"github.com/fsnotify/fsnotify"
)

type Watcher struct {
	*fsnotify.Watcher
	outChan   chan *service.FilesRecord
	watchlist map[string]*service.FilesItem
}

func (w *Watcher) Start() {
	go func() {
		for {
			select {
			// watch for events
			case event := <-w.Events:
				fmt.Printf("EVENT! %#v\n", event)
				// watch for errors
			case err := <-w.Errors:
				fmt.Println("ERROR", err)
			}
		}
	}()
}

func NewWatcher() *Watcher {
	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		fmt.Println("ERROR", err)
	}
	return &Watcher{
		Watcher:   watcher,
		outChan:   make(chan *service.FilesRecord),
		watchlist: make(map[string]*service.FilesItem),
	}
}

func (w *Watcher) Add(item *service.FilesItem) error {
	w.watchlist[item.Path] = item
	return w.Watcher.Add(item.Path)
}
