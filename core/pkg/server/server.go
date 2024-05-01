package server

import (
	"context"
	"fmt"
	"log/slog"
	"net"
	"os"
	"sync"
	"sync/atomic"
	"time"
)

const BufferSize = 32

var defaultLoggerPath atomic.Value

// Server is the core server
type Server struct {
	// ctx is the context for the server
	ctx context.Context

	// listener is the underlying listener
	listener net.Listener

	// wg is the WaitGroup for the server
	wg sync.WaitGroup

	// teardownChan is the channel for signaling and waiting for teardown
	teardownChan chan struct{}

	// shutdownChan is the channel for signaling shutdown
	shutdownChan chan struct{}

	// pidwatchChan is the channel for signaling shutdown of pid watcher
	pidwatchChan chan struct{}
}

// NewServer creates a new server
func NewServer(ctx context.Context, addr string, portFile string, pid int) (*Server, error) {
	listener, err := net.Listen("tcp", addr)
	if err != nil {
		return nil, err
	}

	s := &Server{
		ctx:          ctx,
		listener:     listener,
		wg:           sync.WaitGroup{},
		teardownChan: make(chan struct{}),
		shutdownChan: make(chan struct{}),
		pidwatchChan: make(chan struct{}),
	}

	port := s.listener.Addr().(*net.TCPAddr).Port
	if err := writePortFile(portFile, port); err != nil {
		slog.Error("failed to write port file", "error", err)
		return nil, err
	}

	s.wg.Add(1)
	go s.Serve()
	if pid != 0 {
		s.wg.Add(1)
		go s.WatchParentPid(pid)
	}
	return s, nil
}

func (s *Server) WatchParentPid(pid int) {
	defer s.wg.Done()
outer:
	for {
		select {
		case <-s.pidwatchChan:
			break outer
		case <-time.After(100 * time.Millisecond):
		}
		parentpid := os.Getppid()
		if parentpid != pid {
                        // If the parent went away, lets shutdown immediately
                        // gocritic is warning about uncalled defer for waitgroup
                        // os.Exit(2)  //nolint:go-critic:exitAfterDefer // warning about uncalled defer
                        //go-critic:disable:exitAfterDefer
                        //nolint:go-critic // disable this for now
                        //nolint:gocritic // disable this for now
                        os.Exit(2)  //nolint:all
                        //go-critic:enable:exitAfterDefer
		}
	}
}

func (s *Server) SetDefaultLoggerPath(path string) {
	if path == "" {
		return
	}
	defaultLoggerPath.Store(path)
}

// Serve serves the server
func (s *Server) Serve() {
	defer s.wg.Done()
	slog.Info("server is running", "addr", s.listener.Addr())
	// Run a separate goroutine to handle incoming connections
	for {
		conn, err := s.listener.Accept()
		if err != nil {
			select {
			case <-s.shutdownChan:
				slog.Debug("server shutting down...")
				return
			default:
				slog.Error("failed to accept conn.", "error", err)
			}
		} else {
			s.wg.Add(1)
			go func() {
				nc := NewConnection(s.ctx, conn, s.teardownChan)
				nc.HandleConnection()
				s.wg.Done()
			}()
		}
	}
}

// Close closes the server
func (s *Server) Close() {
	<-s.pidwatchChan
	<-s.teardownChan
	close(s.shutdownChan)
	if err := s.listener.Close(); err != nil {
		slog.Error("failed to Close listener", err)
	}
	s.wg.Wait()
	slog.Info("server is closed")
}

func writePortFile(portFile string, port int) error {
	tempFile := fmt.Sprintf("%s.tmp", portFile)
	f, err := os.Create(tempFile)
	if err != nil {
		err = fmt.Errorf("fail create temp file: %w", err)
		return err
	}

	if _, err = f.WriteString(fmt.Sprintf("sock=%d\n", port)); err != nil {
		err = fmt.Errorf("fail write port: %w", err)
		return err
	}

	if _, err = f.WriteString("EOF"); err != nil {
		err = fmt.Errorf("fail write EOF: %w", err)
		return err
	}

	if err = f.Sync(); err != nil {
		err = fmt.Errorf("fail sync: %w", err)
		return err
	}

	if err := f.Close(); err != nil {
		err = fmt.Errorf("fail close: %w", err)
		return err
	}

	if err = os.Rename(tempFile, portFile); err != nil {
		err = fmt.Errorf("fail rename: %w", err)
		return err
	}
	return nil
}
