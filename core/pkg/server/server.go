package server

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"os"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/pkg/server/listeners"
)

const (
	BufferSize                         = 32
	IntervalCheckParentPidMilliseconds = 100
)

// Server is the top-level object for the wandb-core process.
type Server struct {
	// connNumber is the number of the last connection created.
	//
	// It is used to generate unique IDs for connections.
	connNumber atomic.Int64

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

	// listenOnLocalhost is whether to open a localhost socket even if Unix
	// sockets are supported.
	listenOnLocalhost bool

	// loggerPath is the default logger path
	loggerPath string

	// logLevel is the log level
	logLevel slog.Level
}

type ServerParams struct {
	Commit              string
	EnableDCGMProfiling bool
	ListenOnLocalhost   bool
	LoggerPath          string
	LogLevel            slog.Level
	ParentPID           int

	SentryClient *sentry_ext.Client
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
		parentPID:          params.ParentPID,
		commit:             params.Commit,
		listenOnLocalhost:  params.ListenOnLocalhost,
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
	listenerList, portInfo, err := listeners.Config{
		ParentPID:         s.parentPID,
		ListenOnLocalhost: s.listenOnLocalhost,
	}.MakeListeners()
	if err != nil {
		return err
	}

	if err := portInfo.WriteToFile(portFile); err != nil {
		return err
	}

	if s.parentPID != 0 {
		go s.exitWhenParentIsGone()
	}

	for _, listener := range listenerList {
		s.wg.Add(1)
		go func() {
			defer s.wg.Done()
			s.acceptConnections(listener)
		}()
	}

	// Wait for the signal to shut down.
	<-s.serverLifetimeCtx.Done()
	slog.Info("server is shutting down")

	// Stop accepting new connections.
	for idx, listener := range listenerList {
		if err := listener.Close(); err != nil {
			slog.Error("failed to Close listener", "index", idx, "error", err)
		}
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

		// If a connection is added to the listen queue but closed before we
		// reach here (like if the client suddenly shuts down), the accept()
		// system call returns ECONNABORTED.
		//
		// EMFILE, ENFILE mean we're out of file descriptors.
		// ENOBUFS, ENOMEM mean we're out of memory.
		// These conditions might be temporary, so we sleep and try again.
		if errors.Is(err, syscall.ECONNABORTED) ||
			errors.Is(err, syscall.EMFILE) ||
			errors.Is(err, syscall.ENFILE) ||
			errors.Is(err, syscall.ENOBUFS) ||
			errors.Is(err, syscall.ENOMEM) {
			slog.Warn(
				"server: failed to accept connection",
				"addr", listener.Addr(),
				"error", err,
			)
			time.Sleep(time.Second)
			continue
		}

		// Give up and shut down on any unexpected error.
		if err != nil {
			slog.Error("server: unknown error accepting connection", "error", err)
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
	var id string
	if addr := conn.RemoteAddr().String(); addr != "" {
		id = fmt.Sprintf("%d(%s)", s.connNumber.Add(1), addr)
	} else {
		id = fmt.Sprintf("%d", s.connNumber.Add(1))
	}

	NewConnection(
		s.serverLifetimeCtx,
		s.stopServer,
		ConnectionParams{
			ID:                 id,
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
