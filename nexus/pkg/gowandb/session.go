package gowandb

import (
	"context"
	"fmt"

	"github.com/wandb/wandb/nexus/internal/launcher"
)

type Session struct {
	manager    *Manager
	CoreBinary []byte
}

type SessionOption func(*Session)

func (s *Session) start() {
	ctx := context.Background()
	settings := NewSettings()

	var err error
	_, err = launcher.Launch(s.CoreBinary)
	if err != nil {
		panic("error launching")
	}

	port, err := launcher.Getport()
	if err != nil {
		panic("error getting port")
	}
	addr := fmt.Sprintf("127.0.0.1:%d", port)
	s.manager = NewManager(ctx, settings, addr)
}

func (s *Session) Close() {
	s.manager.Close()
}
