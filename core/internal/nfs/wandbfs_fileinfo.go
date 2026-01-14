package nfs

import (
	"os"
	"time"
)

// WandBFileInfo implements fs.FileInfo for the W&B virtual filesystem.
type WandBFileInfo struct {
	id       uint64
	name     string
	size     int64
	mode     os.FileMode
	modTime  time.Time
	aTime    time.Time
	cTime    time.Time
	isDir    bool
	numLinks int
}

// Name returns the base name of the file.
func (fi *WandBFileInfo) Name() string {
	return fi.name
}

// Size returns the file size in bytes.
func (fi *WandBFileInfo) Size() int64 {
	return fi.size
}

// Mode returns the file mode bits.
func (fi *WandBFileInfo) Mode() os.FileMode {
	return fi.mode
}

// ModTime returns the modification time.
func (fi *WandBFileInfo) ModTime() time.Time {
	return fi.modTime
}

// IsDir returns true if this is a directory.
func (fi *WandBFileInfo) IsDir() bool {
	return fi.isDir
}

// Sys returns nil (no underlying data source).
func (fi *WandBFileInfo) Sys() interface{} {
	return nil
}

// ATime returns the access time (libnfs-go extension).
func (fi *WandBFileInfo) ATime() time.Time {
	return fi.aTime
}

// CTime returns the change time (libnfs-go extension).
func (fi *WandBFileInfo) CTime() time.Time {
	return fi.cTime
}

// NumLinks returns the number of hard links (libnfs-go extension).
func (fi *WandBFileInfo) NumLinks() int {
	return fi.numLinks
}
