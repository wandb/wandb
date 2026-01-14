package nfs

import (
	"net"

	"github.com/smallfz/libnfs-go/fs"
)

// SessionState represents a client network session.
type SessionState interface {
	// Conn returns the current client connection.
	Conn() net.Conn
}

type AuthenticationHandler func(*Auth, *Auth) (*Auth, fs.Creds, error)

type StatService interface {
	// Cwd() string
	// SetCwd(string) error

	SetCurrentHandle(FileHandle4)
	CurrentHandle() FileHandle4

	PushHandle(FileHandle4)
	PeekHandle() (FileHandle4, bool)
	PopHandle() (FileHandle4, bool)

	SetClientId(uint64)
	ClientId() (uint64, bool)

	AddOpenedFile(string, fs.File) uint32
	GetOpenedFile(uint32) fs.FileOpenState
	FindOpenedFiles(string) []fs.FileOpenState
	RemoveOpenedFile(uint32) fs.FileOpenState

	// CloseAndRemoveStallFiles shall close
	//  and remove outdated opened files.
	CloseAndRemoveStallFiles()

	// CleanUp should remove all opened files and reset handle stack.
	CleanUp()
}

// BackendSession has a lifetime exact as the client connection.
type BackendSession interface {
	// Authentication should return an Authentication handler.
	Authentication() AuthenticationHandler

	// GetFS should return a FS implementation.
	// The backend should cache
	GetFS() fs.FS

	// GetStatService returns a StateService in implementation.
	// In development you can return a memfs.Stat instance.
	GetStatService() StatService

	// Close invoked by server when connection closed by any side.
	// Implementation should do some cleaning work at this time.
	Close() error
}

// Backend interface. This is where it starts when building a custom nfs server.
type Backend interface {
	// CreateSession returns a session instance.
	// In development you can return a memfs.Backend instance.
	CreateSession(SessionState) BackendSession
}
