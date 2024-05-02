package gowandb

import (
	"context"
	"fmt"

	"github.com/wandb/wandb/core/pkg/gowandb/opts/runopts"
	"github.com/wandb/wandb/core/pkg/gowandb/opts/sessionopts"
	"github.com/wandb/wandb/core/pkg/gowandb/settings"
	"github.com/wandb/wandb/gowandb/internal/execbin"
	"github.com/wandb/wandb/gowandb/internal/launcher"
)

type Session struct {
	manager *Manager
	execCmd *execbin.ForkExecCmd

	// embed settings parameters which are set by sessionopts options
	sessionopts.SessionParams
}

func (s *Session) start() {
	var execCmd *execbin.ForkExecCmd
	var err error

	ctx := context.Background()
	sessionSettings := s.Settings
	if sessionSettings == nil {
		sessionSettings = settings.NewSettings()
	}

	if s.Address == "" {
		launch := launcher.NewLauncher()
		if len(s.CoreBinary) != 0 {
			execCmd, err = launch.LaunchBinary(s.CoreBinary)
		} else {
			execCmd, err = launch.LaunchCommand("wandb-core")
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

	s.manager = NewManager(ctx, sessionSettings, s.Address)
}

func (s *Session) Close() {
	s.manager.Close()
	if s.execCmd != nil {
		_ = s.execCmd.Wait()
		// TODO(beta): check exit code
	}
}

func (s *Session) NewRun(opts ...runopts.RunOption) (*Run, error) {
	runParams := &runopts.RunParams{}
	for _, opt := range opts {
		opt(runParams)
	}
	run := s.manager.NewRun(runParams)
	run.setup()
	run.init()
	run.start()
	return run, nil
}
