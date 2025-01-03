package wandb

import (
	"context"
	"fmt"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"

	"github.com/wandb/wandb/experimental/go-sdk/internal/connection"
	"github.com/wandb/wandb/experimental/go-sdk/internal/execbin"
	"github.com/wandb/wandb/experimental/go-sdk/internal/launcher"
	"github.com/wandb/wandb/experimental/go-sdk/pkg/settings"
)

type SessionParams struct {
	CoreBinary   []byte
	CoreExecPath string
	Address      string
	Settings     *settings.Settings
}

type Session struct {
	ctx context.Context

	execCmd  *execbin.ForkExecCmd
	binary   []byte
	excePath string
	address  string
	settings *settings.Settings
}

func newSession(params *SessionParams) *Session {
	return &Session{
		ctx:      context.Background(),
		address:  params.Address,
		binary:   params.CoreBinary,
		excePath: params.CoreExecPath,
		settings: params.Settings,
	}
}

func (s *Session) start() {
	if s.address != "" {
		return
	}

	var execCmd *execbin.ForkExecCmd
	var err error

	launch := launcher.NewLauncher()
	switch {
	case len(s.binary) != 0:
		execCmd, err = launch.LaunchBinary(s.binary)
	case s.excePath != "":
		execCmd, err = launch.LaunchCommand(s.excePath)
	default:
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
		// TODO(beta): log error
	} else {
		conn.Close()
	}
	if s.execCmd != nil {
		_ = s.execCmd.Wait()
		// TODO(beta): check exit code
	}
}

func (s *Session) Init(params *RunParams) (*Run, error) {
	runSettings, err := settings.New()
	if err != nil {
		return nil, err
	}
	runSettings.FromSettings(s.settings)
	runSettings.FromSettings(params.Settings)
	run := newRun(s.ctx,
		&runParams{
			settings: runSettings,
			conn:     s.connect(),
			config:   params.Config,
		},
	)
	run.start()
	return run, nil
}
