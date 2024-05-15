package session

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"os/exec"
	"sync/atomic"

	"github.com/wandb/wandb/client/pkg/run"
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

func (s *Session) Start() {
	if s.started.Load() {
		return
	}

	// start the session
	file, err := os.CreateTemp("", ".core-portfile-")
	if err != nil {
		panic(err)
	}
	file.Close()

	args := []string{"--port-filename", file.Name()}

	cmd := exec.Command(s.corePath, args...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		panic(err)
	}

	// read the port from the file
	file, err = os.Open(file.Name())
	if err != nil {
		panic(err)
	}
	defer file.Close()

	var lines []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
	}
	fmt.Println(lines)

	s.started.Store(true)
}

func (s *Session) Close() {
	s.cancel()
	s.started.Store(false)
}

// add a new run

func (s *Session) NewRun(id string) *run.Run {
	return run.New(id)
}

/*
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
*/
