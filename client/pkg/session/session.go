package session

import (
	"context"
	"fmt"
	"sync/atomic"

	"github.com/wandb/wandb/client/internal/launcher"
	"github.com/wandb/wandb/client/pkg/run"
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
	started  atomic.Bool
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

	s.started.Store(true)
	return nil
}

func (s *Session) Close() {
	s.cancel()
	s.started.Store(false)
}

// add a new run

func (s *Session) NewRun(id string) *run.Run {
	return run.New(id)
}
