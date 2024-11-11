package ptysession

import (
	"context"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"os/user"
	"strconv"
	"syscall"
	"time"

	"github.com/creack/pty"
	"github.com/ctrlplanedev/cli/internal/options"
	"github.com/google/uuid"
)

type sessionConfig struct {
	username 	 string
	shell        string
	id           string
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
		log.Printf("Looking up user: %s", config.username)
		usr, err = user.Lookup(config.username)
		if err != nil {
			log.Printf("Failed to lookup user %s: %v", config.username, err)
			return nil, fmt.Errorf("failed to lookup user %s: %v", config.username, err)
		}
	} else {
		log.Printf("Getting current user")
		usr, err = user.Current()
		if err != nil {
			log.Printf("Failed to get current user: %v", err)
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
		log.Printf("Getting shell for user %s", usr.Username)
		config.shell, err = getUserShell(usr.Username)
		if err != nil {
			log.Printf("Failed to get shell for user %s: %v", usr.Username, err)
			return nil, fmt.Errorf("failed to get shell for user %s: %v", usr.Username, err)
		}
	}

	log.Printf("Setting up environment for user %s with shell %s", usr.Username, config.shell)
	env := os.Environ()
	env = append(env, "USER="+usr.Username)
	env = append(env, "SHELL="+config.shell)
	env = append(env, "TERM=xterm-256color")
	env = append(env, "SESSION_ID="+config.id)

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
	log.Printf("Starting PTY session")
	ptmx, err := pty.Start(cmd)
	if err != nil {
		log.Printf("Failed to start PTY: %v", err)
		return nil, fmt.Errorf("failed to start PTY: %v", err)
	}

	if config.size != nil {
		if err := pty.Setsize(ptmx, config.size); err != nil {
			log.Printf("Failed to set terminal size: %v", err)
			return nil, fmt.Errorf("failed to set terminal size: %v", err)
		}
	}

	// Create a cancellable context
	ctx, cancel := context.WithCancel(context.Background())

	sessionID := config.id
	if sessionID == "" {
		sessionID = uuid.New().String()
	}
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

	log.Printf("Successfully started session %s", sessionID)
	return session, nil
}

func (s *Session) SetSize(size *pty.Winsize) {
	if err := pty.Setsize(s.Pty, size); err != nil {
		log.Printf("Failed to set terminal size: %v", err)
	}
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
					log.Printf("PTY read error: %v", err)
				}
				s.CancelFunc()
				return
			}
			s.LastActivity = time.Now()
			select {
			case s.Stdout <- buf[:n]:
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
					log.Printf("PTY write error: %v", err)
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

	log.Printf("Session for user %s ended", strconv.FormatUint(uint64(s.Cmd.SysProcAttr.Credential.Uid), 10))
}
