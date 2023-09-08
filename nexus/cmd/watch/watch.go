package main

import (
	"fmt"
	"github.com/wandb/wandb/nexus/pkg/service"
)
import "github.com/wandb/wandb/nexus/internal/watcher"

// main
func main() {

	// creates a new file watcher
	watch := watcher.NewWatcher()
	defer func(watch *watcher.Watcher) {
		err := watch.Close()
		if err != nil {
			fmt.Println("ERROR", err)
		}
	}(watch)
	//
	watch.Start()
	// out of the box fsnotify can watch a single file, or a single directory
	item := &service.FilesItem{
		Path:   "/Users/dimaduev/dev/sdk/file.txt",
		Policy: service.FilesItem_END,
	}
	if err := watch.Add(item); err != nil {
		fmt.Println("ERROR", err)
	}

	<-make(chan struct{})
}
