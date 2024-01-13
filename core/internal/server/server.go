package server

import (
	"context"
	"fmt"
	"log/slog"
	"net"
	"os"
	"sync"

	"github.com/wandb/wandb/core/internal/server/connection"
)

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
}

func logError(log *slog.Logger, msg string, err error) {
	log.LogAttrs(context.Background(),
		slog.LevelError,
		msg,
		slog.String("error", err.Error()))
}

func writePortFile(portFile string, port int) {
	tempFile := fmt.Sprintf("%s.tmp", portFile)
	f, err := os.Create(tempFile)
	if err != nil {
		logError(slog.Default(), "fail create", err)
	}
	defer func(f *os.File) {
		_ = f.Close()
	}(f)

	if _, err = f.WriteString(fmt.Sprintf("sock=%d\n", port)); err != nil {
		logError(slog.Default(), "fail write", err)
	}

	if _, err = f.WriteString("EOF"); err != nil {
		logError(slog.Default(), "fail write EOF", err)
	}

	if err = f.Sync(); err != nil {
		logError(slog.Default(), "fail sync", err)
	}

	if err = os.Rename(tempFile, portFile); err != nil {
		logError(slog.Default(), "fail rename", err)
	}
	// slog.Info("wrote port file", "file", portFile, "port", port)
}

// NewServer creates a new server
func NewServer(ctx context.Context, addr string, portFile string) *Server {
	listener, err := net.Listen("tcp", addr)
	if err != nil {
		slog.Error("can not listen", "error", err)
		// TODO: handle error
	}

	s := &Server{
		ctx:          ctx,
		listener:     listener,
		wg:           sync.WaitGroup{},
		teardownChan: make(chan struct{}),
		shutdownChan: make(chan struct{}),
	}

	port := s.listener.Addr().(*net.TCPAddr).Port
	writePortFile(portFile, port)
	s.wg.Add(1)
	go s.Serve()
	return s
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
				nc := connection.NewConnection(s.ctx, conn, s.teardownChan)
				nc.HandleConnection()
				s.wg.Done()
			}()
		}
	}
}

// Close closes the server
func (s *Server) Close() {
	<-s.teardownChan
	close(s.shutdownChan)
	if err := s.listener.Close(); err != nil {
		slog.Error("failed to Close listener", err)
	}
	s.wg.Wait()
	slog.Info("server is closed")
}
