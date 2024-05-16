package session

import (
	"context"
	"fmt"
	"sync/atomic"

	"github.com/wandb/wandb/client/internal/connection"
	"github.com/wandb/wandb/client/internal/launcher"
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

// Start launches the core service and sets up the session connection to the
// server. If the session has already been started, this function is a no-op.
func (s *Session) Start() error {
	if s.started.Load() {
		return nil
	}

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
	fmt.Println("sent teardown request", exitCode)
	s.started.Store(false)
}

// connect establishes a connection to the server.
func (s *Session) connect() (*connection.Connection, error) {
	conn, err := connection.New(s.ctx, s.address)
	if err != nil {
		return nil, err
	}
	return conn, nil
}
