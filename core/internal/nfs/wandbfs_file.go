package nfs

import (
	"io"
	"os"

	"github.com/smallfz/libnfs-go/fs"
)

// WandBFile implements fs.File for read-only access to W&B artifacts.
type WandBFile struct {
	wfs    *WandBFS
	node   *VirtualNode
	fi     *WandBFileInfo
	pos    int64
	data   []byte // For files that have content (like metadata.json)
	closed bool
}

// newWandBFile creates a new WandBFile.
func newWandBFile(wfs *WandBFS, node *VirtualNode, data []byte) *WandBFile {
	return &WandBFile{
		wfs:  wfs,
		node: node,
		fi:   node.GetFileInfo(),
		data: data,
	}
}

// Name returns the file name.
func (f *WandBFile) Name() string {
	return f.fi.name
}

// Stat returns the file info.
func (f *WandBFile) Stat() (fs.FileInfo, error) {
	return f.fi, nil
}

// Read reads data from the file.
// For regular artifact files, content reading is not implemented yet.
// For metadata.json files, we return the JSON content.
func (f *WandBFile) Read(p []byte) (int, error) {
	if f.closed {
		return 0, os.ErrClosed
	}

	if f.fi.IsDir() {
		return 0, io.EOF
	}

	// If we have data (like metadata.json), read from it
	if f.data != nil {
		if f.pos >= int64(len(f.data)) {
			return 0, io.EOF
		}
		n := copy(p, f.data[f.pos:])
		f.pos += int64(n)
		return n, nil
	}

	// For regular artifact files, content reading is not implemented
	return 0, io.EOF
}

// Write is not supported (read-only filesystem).
func (f *WandBFile) Write(p []byte) (int, error) {
	return 0, os.ErrPermission
}

// Seek sets the offset for the next Read.
func (f *WandBFile) Seek(offset int64, whence int) (int64, error) {
	if f.closed {
		return 0, os.ErrClosed
	}

	var newPos int64
	switch whence {
	case io.SeekStart:
		newPos = offset
	case io.SeekCurrent:
		newPos = f.pos + offset
	case io.SeekEnd:
		if f.data != nil {
			newPos = int64(len(f.data)) + offset
		} else {
			newPos = f.fi.size + offset
		}
	default:
		return 0, os.ErrInvalid
	}

	if newPos < 0 {
		return 0, os.ErrInvalid
	}

	f.pos = newPos
	return f.pos, nil
}

// Truncate is not supported (read-only filesystem).
func (f *WandBFile) Truncate() error {
	return os.ErrPermission
}

// Sync is a no-op for read-only filesystem.
func (f *WandBFile) Sync() error {
	return nil
}

// Close closes the file.
func (f *WandBFile) Close() error {
	f.closed = true
	return nil
}

// Readdir reads directory entries.
func (f *WandBFile) Readdir(n int) ([]fs.FileInfo, error) {
	if f.closed {
		return nil, os.ErrClosed
	}

	if !f.fi.IsDir() {
		return nil, io.EOF
	}

	// Ensure the directory is loaded
	if err := f.wfs.ensureLoaded(f.node); err != nil {
		return nil, err
	}

	infos := f.node.ChildFileInfos()
	result := make([]fs.FileInfo, len(infos))
	for i, info := range infos {
		result[i] = info
	}

	return result, nil
}
