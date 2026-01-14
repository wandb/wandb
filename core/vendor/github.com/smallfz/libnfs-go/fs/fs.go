// Backend interface. To build a customized NFS server you need to implement these.
package fs

import (
	"io"
	"os"
	"time"
)

type Creds interface {
	Host() string
	Uid() uint32
	Gid() uint32
	Groups() []uint32
}

type FileInfo interface {
	os.FileInfo
	ATime() time.Time
	CTime() time.Time
	NumLinks() int
}

type File interface {
	Name() string
	Stat() (FileInfo, error)
	io.ReadWriteCloser
	io.Seeker
	Truncate() error
	Sync() error
	Readdir(int) ([]FileInfo, error)
}

type WithId interface {
	Id() uint64
}

// FS is the most essential interface that need to be implemeted in a derived nfs server.
type FS interface {
	// SetCreds is called before all other methods to indicate the credentials of the client.
	SetCreds(Creds)

	Open(string) (File, error)
	OpenFile(string, int, os.FileMode) (File, error)
	Stat(string) (FileInfo, error)
	Chmod(string, os.FileMode) error
	Chown(string, int, int) error
	Symlink(string, string) error
	Readlink(string) (string, error)
	Link(string, string) error
	Rename(string, string) error
	Remove(string) error
	MkdirAll(string, os.FileMode) error

	// GetFileId returns an unique id of the file in implementing.
	GetFileId(FileInfo) uint64

	// GetRootHandle returns the handle of the root node.
	GetRootHandle() []byte

	// GetHandle returns the handle of the specified file.
	GetHandle(FileInfo) ([]byte, error)

	// ResolveHandle translate the giving handle to full path of the corresponding file.
	ResolveHandle([]byte) (string, error)

	// Attributes returns the FS' attributes that can be edited.
	Attributes() *Attributes
}

type FSWithId interface {
	FS
	WithId
}

type AllowLink interface {
	Lstat(string) (FileInfo, error)
	Symlink(string, string) error
}

// https://datatracker.ietf.org/doc/html/rfc7530#section-5.6
type Attributes struct {
	LinkSupport     bool   // id: 5
	SymlinkSupport  bool   // id: 6
	ChownRestricted bool   // id: 18
	MaxName         uint32 // id: 29
	MaxRead         uint64 // id: 30
	MaxWrite        uint64 // id: 31
	NoTrunc         bool   // id: 34
}
