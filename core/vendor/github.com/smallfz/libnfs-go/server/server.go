// NFS server implements nfs v4.0.
//
// Package server provides a server implementation of nfs v4.
//
//	import (
//		"fmt"
//		"github.com/smallfz/libnfs-go/log"
//		"github.com/smallfz/libnfs-go/memfs"
//		"github.com/smallfz/libnfs-go/server"
//		"os"
//	)
//
//	func main() {
//		mfs := memfs.NewMemFS()
//		backend := memfs.NewBackend(mfs)
//
//		mfs.MkdirAll("/mount", os.FileMode(0755))
//		mfs.MkdirAll("/test", os.FileMode(0755))
//		mfs.MkdirAll("/test2", os.FileMode(0755))
//		mfs.MkdirAll("/many", os.FileMode(0755))
//
//		perm := os.FileMode(0755)
//		for i := 0; i < 256; i++ {
//	     	mfs.MkdirAll(fmt.Sprintf("/many/sub-%d", i+1), perm)
//		}
//
//		svr, err := server.NewServerTCP(2049, backend)
//		if err != nil {
//	     	log.Errorf("server.NewServerTCP: %v", err)
//	     	return
//		}
//
//		if err := svr.Serve(); err != nil {
//	     	log.Errorf("svr.Serve: %v", err)
//		}
//	}
package server

import (
	"context"
	"fmt"
	"net"

	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

type Server struct {
	listener net.Listener
	backend  nfs.Backend
}

func NewServerTCP(address string, backend nfs.Backend) (*Server, error) {
	ln, err := net.Listen("tcp", address)
	if err != nil {
		return nil, fmt.Errorf("net.Listen: %w", err)
	}
	return NewServer(ln, backend)
}

// NewServer returns a new server with the given listener (e.g. net.Listen, tls.Listen, etc.)
func NewServer(l net.Listener, backend nfs.Backend) (*Server, error) {
	return &Server{listener: l, backend: backend}, nil
}

func (s *Server) Serve() error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	defer s.listener.Close()

	log.Infof("Serving at %s ...", s.listener.Addr())

	for {
		if conn, err := s.listener.Accept(); err != nil {
			return fmt.Errorf("listener.Accept: %w", err)
		} else {
			go func() {
				defer conn.Close()
				if err := handleSession(ctx, s.backend, conn); err != nil {
					log.Errorf("handleSession: %v", err)
				}
			}()
		}
	}
}
