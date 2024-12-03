package gowandb

import (
	"context"
	"fmt"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"github.com/wandb/wandb/experimental/client-go/internal/connection"
	"github.com/wandb/wandb/experimental/client-go/internal/execbin"
	"github.com/wandb/wandb/experimental/client-go/internal/launcher"
	"github.com/wandb/wandb/experimental/client-go/internal/uuid"
	"github.com/wandb/wandb/experimental/client-go/pkg/opts/runopts"
	"github.com/wandb/wandb/experimental/client-go/pkg/settings"
)

type SessionParams struct {
	CoreBinary []byte
	Address    string
	Settings   *settings.SettingsWrap
}

type Session struct {
	ctx context.Context

	execCmd    *execbin.ForkExecCmd
	coreBinary []byte
	address    string
	settings   *settings.SettingsWrap
}

func (s *Session) start() {
	if s.address == "" {
		return
	}
	var execCmd *execbin.ForkExecCmd
	var err error

	launch := launcher.NewLauncher()
	if len(s.coreBinary) != 0 {
		execCmd, err = launch.LaunchBinary(s.coreBinary)
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
	s.address = fmt.Sprintf("127.0.0.1:%d", port)
}

func (s *Session) connect() *connection.Connection {
	conn, err := connection.NewConnection(s.ctx, s.address)
	// slog.Info("Connecting to server", "conn", conn.Conn.RemoteAddr().String())
	if err != nil {
		panic(err)
	}
	return conn
}

func (s *Session) Close() {
	conn := s.connect()
	if err := conn.Send(&spb.ServerRequest{
		ServerRequestType: &spb.ServerRequest_InformTeardown{
			InformTeardown: &spb.ServerInformTeardownRequest{},
		},
	}); err != nil {
		// slog.Error("error sending teardown request", "err", err)
	}
	conn.Close()

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

	// make a copy of the base manager settings
	runSettings := s.settings.Copy()
	if runParams.RunID != nil {
		runSettings.SetRunID(*runParams.RunID)
	} else if runSettings.RunId == nil {
		runSettings.SetRunID(uuid.GenerateUniqueID(8))
	}

	conn := s.connect()
	run := NewRun(s.ctx, runSettings.Settings, conn, runParams)
	run.setup()
	run.init()
	run.start()
	return run, nil
}
