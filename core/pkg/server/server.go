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
	// ctx is the context for the server. It is used to signal
	// the server to shutdown
	ctx context.Context

	// cancel is the cancel function for the server
	cancel context.CancelFunc

	// listener is the underlying listener
	listener net.Listener

	// wg is the WaitGroup to wait for all connections to finish
	// and for the serve goroutine to finish
	wg sync.WaitGroup
}

// NewServer creates a new server
func NewServer(ctx context.Context, addr string, portFile string) (*Server, error) {
	ctx, cancel := context.WithCancel(ctx)

	listener, err := net.Listen("tcp", addr)
	if err != nil {
		cancel()
		return nil, err
	}

	s := &Server{
		ctx:      ctx,
		cancel:   cancel,
		listener: listener,
		wg:       sync.WaitGroup{},
	}

	port := s.listener.Addr().(*net.TCPAddr).Port
	if err := writePortFile(portFile, port); err != nil {
		slog.Error("failed to write port file", "error", err)
		return nil, err
	}

	return s, nil
}

func (s *Server) SetDefaultLoggerPath(path string) {
	if path == "" {
		return
	}
	defaultLoggerPath.Store(path)
}

// Serve starts the server
func (s *Server) Start() {
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		s.serve()
	}()
}

func (s *Server) serve() {
	slog.Info("server is running", "addr", s.listener.Addr())
	// Run a separate goroutine to handle incoming connections
	for {
		conn, err := s.listener.Accept()
		if err != nil {
			select {
			case <-s.ctx.Done():
				slog.Debug("server shutting down...")
				return
			default:
				slog.Error("failed to accept conn.", "error", err)
			}
		} else {
			s.wg.Add(1)
			go func() {
				nc := NewConnection(s.ctx, s.cancel, conn)
				nc.HandleConnection()
				s.wg.Done()
			}()
		}
	}
}

// Wait waits for a signal to shutdown the server
func (s *Server) Wait() {
	<-s.ctx.Done()
	slog.Info("server is shutting down")
}

// Close closes the server
func (s *Server) Close() {
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
