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

type ServerParams struct {
	ListenIPAddress     string
	PortFilename        string
	ParentPid           int
	SentryClient        *sentry_ext.Client
	Commit              string
	LoggerPath          string
	LogLevel            slog.Level
	EnableDCGMProfiling bool
}

// Server is the core server
type Server struct {
	// serverLifetimeCtx is cancelled when the server should shut down.
	serverLifetimeCtx context.Context

	// stopServer cancels serverLifetimeCtx.
	stopServer context.CancelFunc

	// listener is the underlying listener
	listener net.Listener

	// sentryClient is the client used to report errors to sentry.io
	sentryClient *sentry_ext.Client

	// wg is the WaitGroup to wait for all connections to finish
	// and for the serve goroutine to finish
	wg sync.WaitGroup

	// parentPid is the parent pid to watch and exit if it goes away
	parentPid int

	// commit is the W&B Git commit hash
	commit string

	// loggerPath is the default logger path
	loggerPath string

	// logLevel is the log level
	logLevel slog.Level

	// enableDCGMProfiling is true if DCGM profiling is enabled
	enableDCGMProfiling bool
}

// NewServer creates a new server
func NewServer(params *ServerParams) (*Server, error) {
	if params == nil {
		return nil, errors.New("unconfigured params")
	}
	serverLifetimeCtx, stopServer := context.WithCancel(context.Background())

	listener, err := net.Listen("tcp", params.ListenIPAddress)
	if err != nil {
		stopServer()
		return nil, err
	}

	s := &Server{
		serverLifetimeCtx:   serverLifetimeCtx,
		stopServer:          stopServer,
		listener:            listener,
		wg:                  sync.WaitGroup{},
		parentPid:           params.ParentPid,
		sentryClient:        params.SentryClient,
		commit:              params.Commit,
		loggerPath:          params.LoggerPath,
		logLevel:            params.LogLevel,
		enableDCGMProfiling: params.EnableDCGMProfiling,
	}

	port := s.listener.Addr().(*net.TCPAddr).Port
	if err := writePortFile(params.PortFilename, port); err != nil {
		slog.Error("failed to write port file", "error", err)
		return nil, err
	}

	return s, nil
}

// exitWhenParentIsGone exits the process if the parent process is killed.
func (s *Server) exitWhenParentIsGone() {
	slog.Info("Will exit if parent process dies.", "ppid", s.parentPid)

	for os.Getppid() == s.parentPid {
		time.Sleep(IntervalCheckParentPidMilliseconds * time.Millisecond)
	}

	slog.Info("Parent process exited, terminating service process.")

	// The user process has exited, so there's no need to sync
	// uncommitted data, and we can quit immediately.
	os.Exit(1)
}

func (s *Server) Serve() {
	if s.parentPid != 0 {
		go s.exitWhenParentIsGone()
	}

	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		s.serve()
	}()

	// Wait for the signal to shut down.
	<-s.serverLifetimeCtx.Done()
	slog.Info("server is shutting down")

	// Stop accepting new connections.
	if err := s.listener.Close(); err != nil {
		slog.Error("failed to Close listener", "error", err)
	}

	// Wait for asynchronous work to finish.
	s.wg.Wait()

	slog.Info("server is closed")
}

func (s *Server) serve() {
	slog.Info("server is running", "addr", s.listener.Addr())

	streamMux := stream.NewStreamMux()
	gpuResourceManager := monitor.NewGPUResourceManager(s.enableDCGMProfiling)

	// Run a separate goroutine to handle incoming connections
	for {
		conn, err := s.listener.Accept()
		if err != nil {
			select {
			case <-s.serverLifetimeCtx.Done():
				slog.Debug("server shutting down...")
				return
			default:
				slog.Error("failed to accept conn.", "error", err)
			}
		} else {
			s.wg.Add(1)
			go func() {
				NewConnection(
					s.serverLifetimeCtx,
					s.stopServer,
					ConnectionParams{
						Conn:               conn,
						StreamMux:          streamMux,
						GPUResourceManager: gpuResourceManager,
						SentryClient:       s.sentryClient,
						Commit:             s.commit,
						LoggerPath:         s.loggerPath,
						LogLevel:           s.logLevel,
					},
				).ManageConnectionData()

				s.wg.Done()
			}()
		}
	}
}

func writePortFile(portFile string, port int) error {
	tempFile := fmt.Sprintf("%s.tmp", portFile)
	f, err := os.Create(tempFile)
	if err != nil {
		err = fmt.Errorf("fail create temp file: %w", err)
		return err
	}

	if _, err = fmt.Fprintf(f, "sock=%d\n", port); err != nil {
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
