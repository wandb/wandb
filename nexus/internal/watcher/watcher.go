package watcher

import (
	"fmt"

	"github.com/fsnotify/fsnotify"
)

type Watcher struct {
	*fsnotify.Watcher
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
	return &Watcher{watcher}
}
