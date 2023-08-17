package gowandb

import (
	"context"

	"github.com/wandb/wandb/nexus/pkg/service"
)

// Manager is a collection of components that work together to handle incoming
type Manager struct {
	// ctx is the context for the run
	ctx context.Context

	// addr is the address of the server
	addr string

	// settings for all runs
	settings *SettingsWrap
}

// NewManager creates a new manager with the given settings and responders.
func NewManager(ctx context.Context, settings *SettingsWrap, addr string) *Manager {
	manager := &Manager{
		ctx:      ctx,
		settings: settings,
		addr:     addr,
	}
	return manager
}

func (m *Manager) NewRun() *Run {
	conn := m.Connect(m.ctx)
	run := NewRun(m.ctx, m.settings.Settings, conn)
	return run
}

func (m *Manager) Connect(ctx context.Context) *Connection {
	conn, err := NewConnection(ctx, m.addr)
	// slog.Info("Connecting to server", "conn", conn.Conn.RemoteAddr().String())
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
	conn.Close()
}
