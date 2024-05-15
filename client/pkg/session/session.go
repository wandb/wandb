package session

import (
	"context"
	"fmt"
	"sync/atomic"

	"github.com/wandb/wandb/client/internal/connection"
	"github.com/wandb/wandb/client/internal/launcher"
	"github.com/wandb/wandb/client/pkg/run"
	"github.com/wandb/wandb/core/pkg/service"
)

const (
	localHost = "127.0.0.1"
)

type SessionParams struct {
	CorePath string
	Settings map[string]interface{}
}

type Session struct {
	ctx      context.Context
	cancel   context.CancelFunc
	started  *atomic.Bool
	corePath string
	address  string
	settings map[string]interface{}
}

func New(params *SessionParams) *Session {
	ctx, cancel := context.WithCancel(context.Background())
	return &Session{
		ctx:      ctx,
		cancel:   cancel,
		corePath: params.CorePath,
		settings: params.Settings,
		started:  &atomic.Bool{},
	}
}

func (s *Session) Start() error {
	if s.started.Load() {
		return nil
	}

	launch := launcher.NewLauncher()
	_, err := launch.LaunchCommand(s.corePath)
	if err != nil {
		return err
	}

	port, err := launch.GetPort()
	if err != nil {
		return err
	}
	s.address = fmt.Sprintf("%s:%d", localHost, port)
	fmt.Println("Address: ", s.address)
	s.started.Store(true)
	return nil
}

func (s *Session) Close() {
	if !s.started.Load() {
		return
	}

	conn, err := s.connect()
	if err != nil {
		return
	}

	defer conn.Close()

	serverRecord := service.ServerRequest{
		ServerRequestType: &service.ServerRequest_InformTeardown{
			InformTeardown: &service.ServerInformTeardownRequest{},
		},
	}
	if err := conn.Send(&serverRecord); err != nil {
		return
	}

	s.started.Store(false)
}

func (s *Session) connect() (*connection.Connection, error) {
	conn, err := connection.New(s.ctx, s.address)
	if err != nil {
		return nil, err
	}
	return conn, nil
}

// add a new run

func (s *Session) NewRun(id string) *run.Run {
	return run.New(id)
}
