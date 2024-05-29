package watcher

import (
	"os"
	"time"
)

// FileModToken is a value of a file that usually changes if the file changes.
type FileModToken struct {
	// modTime is the file's mtime (modification time).
	//
	// The precision of this varies by system, and it's very possible for
	// two rapid changes to a file to only modify the mtime once, so this
	// is not guaranteed to change if a file is changed.
	modTime time.Time

	// size is the file's size as reported by Stat().
	//
	// This can be a useful signal if the modTime precision is low.
	size int64
}

func FileModTokenFrom(info os.FileInfo) FileModToken {
	return FileModToken{
		modTime: info.ModTime(),
		size:    info.Size(),
	}
}
