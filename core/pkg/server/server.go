package server

import (
	"context"
	"fmt"
	"log/slog"
	"net"
	"os"
	"sync"
	"sync/atomic"
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

	// ppid is the parent process id
	ppid *int

	// internalTeardownChan is used to signal teardown if the parent process is gone
	internalTeardownChan chan struct{}

	// teardownChan is the channel for signaling and waiting for teardown
	teardownChan chan struct{}

	// shutdownChan is the channel for signaling shutdown
	shutdownChan chan struct{}
}

// NewServer creates a new server
func NewServer(ctx context.Context, addr string, portFile string, ppid *int) (*Server, error) {
	listener, err := net.Listen("tcp", addr)
	if err != nil {
		return nil, err
	}

	s := &Server{
		ctx:          ctx,
		listener:     listener,
		wg:           sync.WaitGroup{},
		ppid:         ppid,
		internalTeardownChan: make(chan struct{}),
		teardownChan: make(chan struct{}),
		shutdownChan: make(chan struct{}),
	}

	port := s.listener.Addr().(*net.TCPAddr).Port
	if err := writePortFile(portFile, port); err != nil {
		slog.Error("failed to write port file", "error", err)
		return nil, err
	}

	s.wg.Add(1)
	go s.Serve()
	return s, nil
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
				fmt.Println("handling connection")
				nc := NewConnection(s.ctx, conn, s.teardownChan)
				nc.HandleConnection()
				fmt.Println("connection closed")
				s.wg.Done()
			}()
		}
	}
}

// Close closes the server
func (s *Server) Close() {
	fmt.Println("waiting to close the server")
	// if there is a parent process, start a goroutine to wait for it to go away,
	// (if it's e.g. killed), in which case we will close the server
	if s.ppid != nil {
		go func() {
			for {
				if os.Getppid() != *s.ppid {
					fmt.Println("parent process is gone, closing the server")
					close(s.internalTeardownChan)
					return
				}
			}
		}()
	}
	// <-s.teardownChan
	// fmt.Println("teardownChan received")

	select {
	case <-s.teardownChan:
		fmt.Println("teardownChan received")
	case <-s.internalTeardownChan:
		fmt.Println("internalTeardownChan received")
	}

	close(s.shutdownChan)
	fmt.Println("shutdownChan closed")
	if err := s.listener.Close(); err != nil {
		slog.Error("failed to Close listener", err)
	}
	fmt.Println("listener closed")
	s.wg.Wait()
	fmt.Println("wg.Wait() done")
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
