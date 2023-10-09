package main

import (
	"fmt"

	"github.com/wandb/wandb/nexus/internal/watcher"
	"github.com/wandb/wandb/nexus/pkg/service"
)

// main
func main() {

	// creates a new file watcher
	watch := watcher.NewWatcher()
	// defer func(watch *watcher.Watcher) {
	// 	watch.Close()
	// }(watch)
	//
	watch.Start()

	item := &service.FilesItem{
		Path:   "/Users/dimaduev/dev/sdk/file.txt",
		Policy: service.FilesItem_LIVE,
	}
	if err := watch.Add(item); err != nil {
		fmt.Println("ERROR", err)
	}

	<-make(chan struct{})
}
