package gowandb

import (
	"context"
	"fmt"

	"github.com/wandb/wandb/nexus/internal/execbin"
	"github.com/wandb/wandb/nexus/internal/launcher"
)

type Session struct {
	manager    *Manager
	CoreBinary []byte
	execCmd    *execbin.ForkExecCmd
	Address    string
	Settings   *SettingsWrap
}

type SessionOption func(*Session)

func (s *Session) start() {
	var execCmd *execbin.ForkExecCmd
	var err error

	ctx := context.Background()
	settings := s.Settings
	if settings == nil {
		settings = NewSettings()
	}

	if s.Address == "" {
		launch := launcher.NewLauncher()
		if len(s.CoreBinary) != 0 {
			execCmd, err = launch.LaunchBinary(s.CoreBinary)
		} else {
			execCmd, err = launch.LaunchCommand("nexus")
		}
		if err != nil {
			panic("error launching")
		}
		s.execCmd = execCmd

		port, err := launch.Getport()
		if err != nil {
			panic("error getting port")
		}
		s.Address = fmt.Sprintf("127.0.0.1:%d", port)
	}

	s.manager = NewManager(ctx, settings, s.Address)
}

func (s *Session) Close() {
	s.manager.Close()
	if s.execCmd != nil {
		_ = s.execCmd.Wait()
		// TODO(beta): check exit code
	}
}
