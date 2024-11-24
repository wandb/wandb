package ptysession

import (
	"context"
	"fmt"
	"io"

	"os"
	"os/exec"
	"os/user"
	"strconv"
	"syscall"
	"time"

	"github.com/charmbracelet/log"
	"github.com/creack/pty"
	"github.com/ctrlplanedev/cli/internal/options"
	"github.com/moby/term"
)

type sessionConfig struct {
	username     string
	shell        string
	size         *pty.Winsize
	closeHandler func()
}

// AsUser sets the username for the session
func AsUser(username string) options.Option {
	return options.NewOptionFunc(func(v interface{}) {
		if c, ok := v.(*sessionConfig); ok {
			c.username = username
		}
	})
}

// WithShell sets the shell for the session
func WithShell(shell string) options.Option {
	return options.NewOptionFunc(func(v interface{}) {
		if c, ok := v.(*sessionConfig); ok {
			c.shell = shell
		}
	})
}

// WithSize sets the terminal size for the session
func WithSize(rows, cols uint16) options.Option {
	return options.NewOptionFunc(func(v interface{}) {
		if c, ok := v.(*sessionConfig); ok {
			if rows == 0 || cols == 0 {
				return
			}
			c.size = &pty.Winsize{
				Rows: rows,
				Cols: cols,
			}
		}
	})
}

func WithCloseHandler(handler func()) options.Option {
	return options.NewOptionFunc(func(v interface{}) {
		if c, ok := v.(*sessionConfig); ok {
			c.closeHandler = handler
		}
	})
}

type Session struct {
	Stdin        chan []byte
	Stdout       chan []byte
	Pty          *os.File
	Cmd          *exec.Cmd
	Ctx          context.Context
	CancelFunc   context.CancelFunc
	LastActivity time.Time
	CreatedAt    time.Time
}

func StartSession(opts ...options.Option) (*Session, error) {
	config := &sessionConfig{
		shell: "",
	}

	for _, opt := range opts {
		opt.Apply(config)
	}

	var usr *user.User
	var err error

	if config.username != "" {
		log.Info("Looking up user", "username", config.username)
		usr, err = user.Lookup(config.username)
		if err != nil {
			log.Error("Failed to lookup user", "username", config.username, "error", err)
			return nil, fmt.Errorf("failed to lookup user %s: %v", config.username, err)
		}
	} else {
		log.Info("Getting current user")
		usr, err = user.Current()
		if err != nil {
			log.Error("Failed to get current user", "error", err)
			return nil, fmt.Errorf("failed to get current user: %v", err)
		}
	}

	// uid, err := strconv.Atoi(usr.Uid)
	// if err != nil {
	// 	return nil, fmt.Errorf("invalid UID: %v", err)
	// }

	// gid, err := strconv.Atoi(usr.Gid)
	// if err != nil {
	// 	return nil, fmt.Errorf("invalid GID: %v", err)
	// }

	if config.shell == "" {
		log.Info("Getting shell for user", "username", usr.Username)
		config.shell, err = getUserShell(usr.Username)
		if err != nil {
			log.Error("Failed to get shell for user", "username", usr.Username, "error", err)
			return nil, fmt.Errorf("failed to get shell for user %s: %v", usr.Username, err)
		}
	}

	log.Info("Setting up environment for user", "username", usr.Username, "shell", config.shell)
	env := os.Environ()
	env = append(env, "USER="+usr.Username)
	env = append(env, "SHELL="+config.shell)
	env = append(env, "TERM=xterm-256color")

	// Ensure proper encoding for websocket transmission
	env = append(env, "LANG=en_US.UTF-8")
	env = append(env, "LC_ALL=en_US.UTF-8")
	env = append(env, "PYTHONUNBUFFERED=1")
	env = append(env, "FORCE_COLOR=1")

	cmd := exec.Command(config.shell)
	cmd.Env = env
	cmd.Dir = usr.HomeDir
	cmd.SysProcAttr = &syscall.SysProcAttr{
		// Credential: &syscall.Credential{
		// 	Uid: uint32(uid),
		// 	Gid: uint32(gid),
		// },
		Setsid: true,
	}

	// Start the PTY session
	log.Info("Starting PTY session")
	ptmx, err := pty.Start(cmd)
	if err != nil {
		log.Error("Failed to start PTY", "error", err)
		return nil, fmt.Errorf("failed to start PTY: %v", err)
	}

	if config.size != nil {
		if err := pty.Setsize(ptmx, config.size); err != nil {
			log.Error("Failed to set terminal size", "error", err)
			return nil, fmt.Errorf("failed to set terminal size: %v", err)
		}
	}

	// Create a cancellable context
	ctx, cancel := context.WithCancel(context.Background())

	now := time.Now()
	session := &Session{
		Stdin:        make(chan []byte, 1024),
		Stdout:       make(chan []byte, 1024),
		Pty:          ptmx,
		Cmd:          cmd,
		Ctx:          ctx,
		CancelFunc:   cancel,
		LastActivity: now,
		CreatedAt:    now,
	}

	// Handle session cleanup
	go func() {
		<-ctx.Done()
		if config.closeHandler != nil {
			config.closeHandler()
		}
	}()
	return session, nil
}

func (s *Session) SetSize(size *pty.Winsize) error {
	oldRows, oldCols, _ := pty.Getsize(s.Pty)
	log.Info("Resizing terminal", "from", fmt.Sprintf("(%dx%d)", oldRows, oldCols), "to", fmt.Sprintf("(%dx%d)", size.Rows, size.Cols))

	if err := term.SetWinsize(s.Pty.Fd(), &term.Winsize{
		Height: size.Rows,
		Width:  size.Cols,
	}); err != nil {
		log.Error("Failed to set terminal size", "error", err)
		return err
	}
	return nil
}

func (s *Session) HandleIO() {
	defer func() {
		close(s.Stdin)
		close(s.Stdout)
		s.Pty.Close()
		s.Cmd.Process.Kill()
		s.CancelFunc()
	}()

	// PTY to Output channel
	go func() {
		buf := make([]byte, 1024)
		for {
			n, err := s.Pty.Read(buf)
			if err != nil {
				if err != io.EOF {
					log.Error("PTY read error", "error", err)
				}
				s.CancelFunc()
				return
			}
			s.LastActivity = time.Now()
			// Create a copy of the data to prevent it from being overwritten
			data := make([]byte, n)
			copy(data, buf[:n])

			select {
			case s.Stdout <- data:
			case <-s.Ctx.Done():
				return
			}
		}
	}()

	// Input channel to PTY
	go func() {
		for {
			select {
			case data := <-s.Stdin:
				s.LastActivity = time.Now()
				_, err := s.Pty.Write(data)
				if err != nil {
					log.Error("PTY write error", "error", err)
					s.CancelFunc()
					return
				}
			case <-s.Ctx.Done():
				return
			}
		}
	}()

	// Wait for session to end
	<-s.Ctx.Done()

	// Wait for the command to exit
	s.Cmd.Wait()

	log.Info("Session for user ended", "uid", strconv.FormatUint(uint64(s.Cmd.SysProcAttr.Credential.Uid), 10))
}
