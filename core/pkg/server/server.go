package server

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"os"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/pkg/monitor"
)

const (
	BufferSize                         = 32
	IntervalCheckParentPidMilliseconds = 100
)

// Server is the top-level object for the wandb-core process.
type Server struct {
	// serverLifetimeCtx is cancelled when the server should shut down.
	serverLifetimeCtx context.Context

	// stopServer cancels serverLifetimeCtx.
	stopServer context.CancelFunc

	// streamMux maps stream IDs to streams.
	streamMux *stream.StreamMux

	// gpuResourceManager manages costly resources for GPU system metrics.
	gpuResourceManager *monitor.GPUResourceManager

	// sentryClient is the client used to report errors to sentry.io
	sentryClient *sentry_ext.Client

	// wg is the WaitGroup to wait for all connections to finish
	// and for the serve goroutine to finish
	wg sync.WaitGroup

	// parentPID is parent process's ID.
	//
	// The server exits if the parent process is gone.
	parentPID int

	// commit is the W&B Git commit hash.
	commit string

	// loggerPath is the default logger path
	loggerPath string

	// logLevel is the log level
	logLevel slog.Level
}

type ServerParams struct {
	ParentPid           int
	SentryClient        *sentry_ext.Client
	Commit              string
	LoggerPath          string
	LogLevel            slog.Level
	EnableDCGMProfiling bool
}

// NewServer creates a new server
func NewServer(params ServerParams) *Server {
	serverLifetimeCtx, stopServer := context.WithCancel(context.Background())

	return &Server{
		serverLifetimeCtx:  serverLifetimeCtx,
		stopServer:         stopServer,
		streamMux:          stream.NewStreamMux(),
		gpuResourceManager: monitor.NewGPUResourceManager(params.EnableDCGMProfiling),
		sentryClient:       params.SentryClient,
		wg:                 sync.WaitGroup{},
		parentPID:          params.ParentPid,
		commit:             params.Commit,
		loggerPath:         params.LoggerPath,
		logLevel:           params.LogLevel,
	}
}

// exitWhenParentIsGone exits the process if the parent process is killed.
func (s *Server) exitWhenParentIsGone() {
	slog.Info("server: will exit if parent process dies", "ppid", s.parentPID)

	for os.Getppid() == s.parentPID {
		time.Sleep(IntervalCheckParentPidMilliseconds * time.Millisecond)
	}

	slog.Info("server: parent process exited, terminating service process")

	// The user process has exited, so there's no need to sync
	// uncommitted data, and we can quit immediately.
	os.Exit(1)
}

func (s *Server) Serve(portFile string) error {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return fmt.Errorf("server: failed to listen on localhost: %v", err)
	}

	portInfo := PortInfo{
		LocalhostPort: listener.Addr().(*net.TCPAddr).Port,
	}
	if err := portInfo.WriteToFile(portFile); err != nil {
		return err
	}

	if s.parentPID != 0 {
		go s.exitWhenParentIsGone()
	}

	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		s.acceptConnections(listener)
	}()

	// Wait for the signal to shut down.
	<-s.serverLifetimeCtx.Done()
	slog.Info("server is shutting down")

	// Stop accepting new connections.
	if err := listener.Close(); err != nil {
		slog.Error("failed to Close listener", "error", err)
	}

	// Wait for asynchronous work to finish.
	s.wg.Wait()

	slog.Info("server is closed")
	return nil
}

// acceptConnections accepts incoming connections on the listener.
//
// It blocks until the listener is closed or an error is encountered.
func (s *Server) acceptConnections(listener net.Listener) {
	slog.Info("server: accepting connections", "addr", listener.Addr())

	for {
		conn, err := listener.Accept()

		if errors.Is(err, net.ErrClosed) {
			slog.Info("server: listener closed", "addr", listener.Addr())
			return
		}

		// We shut down on any error, even though some may be recoverable.
		// From the accept(2) manual pages, these include:
		//
		//   - EMFILE, ENFILE (out of file descriptors)
		//   - ENOBUFS, ENOMEM (out of memory)
		//
		// Maybe ECONNABORTED as well.
		//
		// Though in theory these are recoverable, we don't have a clean way
		// to distinguish them from other errors in Go, and we want to avoid
		// busy-looping in case Accept() immediately returns an error
		// each time it is called.
		if err != nil {
			slog.Error("server: failed to accept connection", "error", err)
			s.stopServer()
			return
		}

		s.wg.Add(1)
		go func() {
			s.handleConnection(conn)
			s.wg.Done()
		}()
	}
}

// handleConnection processes incoming data on a connection.
//
// This blocks until the connection closes.
func (s *Server) handleConnection(conn net.Conn) {
	NewConnection(
		s.serverLifetimeCtx,
		s.stopServer,
		ConnectionParams{
			Conn:               conn,
			StreamMux:          s.streamMux,
			GPUResourceManager: s.gpuResourceManager,
			SentryClient:       s.sentryClient,
			Commit:             s.commit,
			LoggerPath:         s.loggerPath,
			LogLevel:           s.logLevel,
		},
	).ManageConnectionData()
}
