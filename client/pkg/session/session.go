package session

import (
	"context"

	"github.com/wandb/wandb/client/internal/connection"
	"github.com/wandb/wandb/core/pkg/service"
)

// Params holds parameters for creating a new Session
type Params struct {
	Address string
}

// Session manages the lifecycle of a connection session to the internal "wandb-core" process
type Session struct {
	ctx    context.Context
	cancel context.CancelFunc

	// conn is the connection to the server
	conn *connection.Connection

	// address is the address of the server that the session is connected to
	address string
}

// New creates a new Session with the provided parameters
func New(params Params) *Session {
	ctx, cancel := context.WithCancel(context.Background())

	s := &Session{
		ctx:     ctx,
		cancel:  cancel,
		address: params.Address,
	}
	return s
}

// Teardown sends a teardown request to the wandb-core service
//
// The exitCode parameter is the exit code that the wandb-core service should
func (s *Session) Teardown(exitCode int32) error {
	// create a connection to the server and send a teardown request
	conn, err := s.connect()
	if err != nil {
		return err
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
		return err
	}

	return nil
}

// connect establishes a connection to the wandb-core service.
func (s *Session) connect() (*connection.Connection, error) {
	if s.conn != nil {
		return s.conn, nil
	}
	conn, err := connection.New(s.ctx, s.address)
	if err != nil {
		return nil, err
	}
	s.conn = conn
	return s.conn, nil
}
