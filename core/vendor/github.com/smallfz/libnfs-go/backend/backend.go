package backend

import (
	"github.com/smallfz/libnfs-go/fs"
	"github.com/smallfz/libnfs-go/nfs"
)

type backendSession struct {
	vfs            fs.FS
	stat           *Stat
	authentication nfs.AuthenticationHandler
}

func (s *backendSession) Close() error {
	if s.stat != nil {
		s.stat.CleanUp()
	}
	return nil
}

func (s *backendSession) Authentication() nfs.AuthenticationHandler {
	return s.authentication
}

func (s *backendSession) GetFS() fs.FS {
	return s.vfs
}

func (s *backendSession) GetStatService() nfs.StatService {
	return s.stat
}

type Backend struct {
	vfsLoader      func() fs.FS
	authentication nfs.AuthenticationHandler
}

// New creates a new Backend instance.
func New(vfsLoader func() fs.FS, authentication nfs.AuthenticationHandler) *Backend {
	return &Backend{
		vfsLoader:      vfsLoader,
		authentication: authentication,
	}
}

func (b *Backend) CreateSession(state nfs.SessionState) nfs.BackendSession {
	return &backendSession{
		vfs:            b.vfsLoader(),
		stat:           new(Stat),
		authentication: b.authentication,
	}
}
