package session

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"sync/atomic"

	"github.com/wandb/wandb/client/internal/connection"
	"github.com/wandb/wandb/client/internal/launcher"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

const (
	localHost = "127.0.0.1"
)

// SessionParams holds parameters for creating a new Session
type SessionParams struct {
	CorePath string
}

// Session manages the lifecycle of a connection session
type Session struct {
	ctx    context.Context
	cancel context.CancelFunc

	logger     *observability.CoreLogger
	loggerFile *os.File

	// started is an atomic boolean that indicates whether the session has been
	// started
	started *atomic.Bool

	// corePath is the path to the core binary that the session will launch
	corePath string

	// address is the address of the server that the session is connected to
	address string
}

// New creates a new Session with the provided parameters
func New(params *SessionParams) *Session {
	ctx, cancel := context.WithCancel(context.Background())
	return &Session{
		ctx:      ctx,
		cancel:   cancel,
		corePath: params.CorePath,
		started:  &atomic.Bool{},
	}
}

// Address returns the address of the session
func (s *Session) Address() string {
	return s.address
}

func (s *Session) LogFileName() string {
	if s.loggerFile == nil {
		return ""
	}
	return s.loggerFile.Name()
}

// setUpLogger sets up the default logger for the session
func (s *Session) setUpLogger() {
	if file, _ := observability.GetLoggerPath("client"); file != nil {
		level := slog.LevelInfo
		if os.Getenv("WANDB_DEBUG") != "" {
			level = slog.LevelDebug
		}
		opts := &slog.HandlerOptions{
			Level:     level,
			AddSource: false,
		}
		logger := slog.New(slog.NewJSONHandler(file, opts))
		slog.SetDefault(logger)
		slog.Info("corePath", "corePath", s.corePath)

		s.logger = observability.NewCoreLogger(
			logger,
			observability.WithTags(observability.Tags{}),
			observability.WithCaptureMessage(observability.CaptureMessage),
			observability.WithCaptureException(observability.CaptureException),
		)
		s.loggerFile = file
	}
}

// Start launches the core service and sets up the session connection to the
// server. If the session has already been started, this function is a no-op.
func (s *Session) Start() error {
	if s.started.Load() {
		return nil
	}

	s.setUpLogger()
	s.logger.CaptureInfo("using wandb-client")

	launch := launcher.New()
	_, err := launch.LaunchCommand(s.corePath)
	if err != nil {
		return err
	}

	port, err := launch.GetPort()
	if err != nil {
		return err
	}
	s.address = fmt.Sprintf("%s:%d", localHost, port)
	s.logger.Info("started session", "address", s.address)
	s.started.Store(true)
	return nil
}

// Close gracefully shuts down the session. If the session has not been started,
// this function is a no-op.
func (s *Session) Close(exitCode int32) {
	if !s.started.Load() {
		return
	}

	conn, err := s.connect()
	if err != nil {
		return
	}

	defer conn.Close()

	request := service.ServerRequest{
		ServerRequestType: &service.ServerRequest_InformTeardown{
			InformTeardown: &service.ServerInformTeardownRequest{
				ExitCode: exitCode,
			},
		},
	}
	if err := conn.Send(&request); err != nil {
		return
	}
	s.logger.Info("sent teardown request", "exitCode", exitCode)
	s.started.Store(false)
	s.loggerFile.Close()
	s.logger = nil
}

// connect establishes a connection to the server.
func (s *Session) connect() (*connection.Connection, error) {
	conn, err := connection.New(s.ctx, s.address)
	if err != nil {
		return nil, err
	}
	return conn, nil
}
