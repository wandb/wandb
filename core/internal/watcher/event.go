package watcher

import (
	"io/fs"

	fw "github.com/radovskyb/watcher"
)

type Event struct {
	fw.Event
}

func (e *Event) IsWrite() bool {
	return e.Event.Op == fw.Write
}

func (e *Event) IsRead() bool {
	return e.Event.Op == fw.Write
}

func (e *Event) IsCreate() bool {
	return e.Event.Op == fw.Create
}

type EventFileInfo struct {
	fs.FileInfo
	name string
}

func (e *EventFileInfo) Name() string {
	return e.name
}
