package nfs

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"

	"github.com/smallfz/libnfs-go/fs"
)

// WandBFile implements fs.File for read-only access to W&B artifacts.
type WandBFile struct {
	wfs       *WandBFS
	node      *VirtualNode
	fi        *WandBFileInfo
	pos       int64
	data      []byte   // For files that have content (like metadata.json)
	localFile *os.File // For cached artifact files
	closed    bool
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
// For metadata.json files, we return the JSON content from memory.
// For regular artifact files, we download to cache and read from disk.
func (f *WandBFile) Read(p []byte) (int, error) {
	if f.closed {
		slog.Debug("Read: file closed", "name", f.fi.name)
		return 0, os.ErrClosed
	}

	if f.fi.IsDir() {
		slog.Debug("Read: is directory", "name", f.fi.name)
		return 0, io.EOF
	}

	// If we have data (like metadata.json), read from it
	if f.data != nil {
		if f.pos >= int64(len(f.data)) {
			slog.Debug("Read: EOF on in-memory data",
				"name", f.fi.name,
				"pos", f.pos,
				"dataLen", len(f.data))
			return 0, io.EOF
		}
		n := copy(p, f.data[f.pos:])
		f.pos += int64(n)
		slog.Info("Read: from in-memory data",
			"name", f.fi.name,
			"bytesRead", n,
			"newPos", f.pos)
		return n, nil
	}

	slog.Info("Read: need to read from cache",
		"name", f.fi.name,
		"nodeType", f.node.Type,
		"hasLocalFile", f.localFile != nil)

	// Regular artifact file - read from cache
	if f.localFile == nil {
		if err := f.ensureCached(); err != nil {
			slog.Error("Read: ensureCached failed",
				"name", f.fi.name,
				"error", err)
			return 0, err
		}
	}

	// Read from local cached file at current position
	n, err := f.localFile.ReadAt(p, f.pos)
	if n > 0 {
		f.pos += int64(n)
	}
	// ReadAt returns io.EOF when reaching end, but Read should only
	// return EOF when no bytes were read
	if err == io.EOF && n > 0 {
		err = nil
	}
	slog.Debug("Read: from cached file",
		"name", f.fi.name,
		"bytesRead", n,
		"newPos", f.pos,
		"error", err)
	return n, err
}

// ensureCached downloads the file to cache if not already cached.
func (f *WandBFile) ensureCached() error {
	path := f.node.FullPath()

	if f.node.DirectURL == "" || f.node.MD5 == "" {
		slog.Warn("file missing download info",
			"path", path,
			"hasDirectURL", f.node.DirectURL != "",
			"hasMD5", f.node.MD5 != "")
		return fmt.Errorf("file %s: missing download info (directUrl or md5)", path)
	}

	slog.Debug("downloading file to cache",
		"path", path,
		"size", f.node.FileSize,
		"md5", f.node.MD5[:8]+"...")

	cachePath, err := f.wfs.contentCache.GetOrDownload(
		context.Background(),
		f.node.MD5,
		f.node.DirectURL,
		f.node.FileSize,
	)
	if err != nil {
		slog.Error("failed to download file",
			"path", path,
			"error", err)
		return fmt.Errorf("downloading %s: %w", path, err)
	}

	slog.Debug("file cached successfully",
		"path", path,
		"cachePath", cachePath)

	f.localFile, err = os.Open(cachePath)
	if err != nil {
		slog.Error("failed to open cached file",
			"path", path,
			"cachePath", cachePath,
			"error", err)
	}
	return err
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
	if f.localFile != nil {
		return f.localFile.Close()
	}
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
