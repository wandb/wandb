package client

import (
	"context"
	"log/slog"

	"github.com/wandb/wandb/nexus/pkg/service"
)

// Manager is a collection of components that work together to handle incoming
type Manager struct {
	// ctx is the context for the run
	ctx context.Context

	// addr is the address of the server
	addr string
}

// NewManager creates a new manager with the given settings and responders.
func NewManager(ctx context.Context, addr string) *Manager {
	manager := &Manager{
		ctx:  ctx,
		addr: addr,
	}
	return manager
}

func (m *Manager) NewRun(ctx context.Context, settings *service.Settings) *Run {
	conn := m.Connect(ctx)
	run := NewRun(ctx, settings, conn)
	return run
}

func (m *Manager) Connect(ctx context.Context) *Connection {
	conn, err := NewConnection(ctx, m.addr)
	slog.Info("Connecting to server", "conn", conn.Conn.RemoteAddr().String())
	if err != nil {
		panic(err)
	}
	return conn
}

func (m *Manager) Close() {
	conn := m.Connect(m.ctx)
	serverRecord := service.ServerRequest{
		ServerRequestType: &service.ServerRequest_InformTeardown{InformTeardown: &service.ServerInformTeardownRequest{}},
	}
	err := conn.Send(&serverRecord)
	if err != nil {
		return
	}
}
