package monitor

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// collectorStartupTimeout bounds how long Client waits for the
	// sidecar process to print its address.
	collectorStartupTimeout = 5 * time.Second

	// collectorShutdownTimeout bounds how long Release waits for the
	// sidecar process to exit after asking it to tear down.
	collectorShutdownTimeout = 5 * time.Second

	// stderrTailSize is how much of the sidecar's stderr is kept for the
	// error reported when it fails to start.
	stderrTailSize = 1024
)

type SymonResourceManagerRef int

// SymonResourceManager manages the wandb-symon sidecar process.
//
// The sidecar runs while at least one reference is held and is started
// again by the next Client call after it exits.
type SymonResourceManager struct {
	mu sync.Mutex

	collectorProcess *exec.Cmd
	collectorConn    *grpc.ClientConn
	collectorClient  spb.SystemMonitorServiceClient

	// collectorExited is closed when collectorProcess exits.
	collectorExited chan struct{}

	refs      map[SymonResourceManagerRef]struct{}
	nextRefId int

	enableDCGMProfiling bool
}

func NewSymonResourceManager(enableDCGMProfiling bool) *SymonResourceManager {
	return &SymonResourceManager{
		refs:                map[SymonResourceManagerRef]struct{}{},
		enableDCGMProfiling: enableDCGMProfiling,
	}
}

// Acquire registers a reference to the sidecar.
func (m *SymonResourceManager) Acquire() SymonResourceManagerRef {
	m.mu.Lock()
	defer m.mu.Unlock()

	refID := SymonResourceManagerRef(m.nextRefId)
	m.nextRefId++
	m.refs[refID] = struct{}{}
	return refID
}

// Client returns a client for the sidecar, starting it if it is not
// running. ctx bounds the start.
func (m *SymonResourceManager) Client(
	ctx context.Context,
	ref SymonResourceManagerRef,
) (spb.SystemMonitorServiceClient, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	if _, ok := m.refs[ref]; !ok {
		return nil, errors.New("monitor: symon reference was released")
	}

	if m.collectorExited != nil {
		select {
		case <-m.collectorExited:
			_ = m.collectorConn.Close()
			m.collectorProcess = nil
			m.collectorConn = nil
			m.collectorClient = nil
			m.collectorExited = nil
		default:
		}
	}

	if m.collectorConn == nil {
		if err := m.startCollector(ctx); err != nil {
			return nil, err
		}
	}
	return m.collectorClient, nil
}

func (m *SymonResourceManager) Release(ref SymonResourceManagerRef) {
	m.mu.Lock()
	defer m.mu.Unlock()

	delete(m.refs, ref)
	if len(m.refs) > 0 || m.collectorConn == nil {
		return
	}

	proc := m.collectorProcess
	exited := m.collectorExited
	conn := m.collectorConn
	client := m.collectorClient
	m.collectorProcess = nil
	m.collectorExited = nil
	m.collectorConn = nil
	m.collectorClient = nil

	go func() {
		ctx, cancel := context.WithTimeout(
			context.Background(),
			collectorShutdownTimeout,
		)
		defer cancel()

		_, _ = client.TearDown(ctx, &spb.TearDownRequest{})
		_ = conn.Close()

		context.AfterFunc(ctx, func() { _ = proc.Process.Kill() })
		<-exited
	}()
}

func (m *SymonResourceManager) startCollector(ctx context.Context) error {
	if err := ctx.Err(); err != nil {
		return err
	}

	cmdPath, err := symonPath()
	if err != nil {
		return fmt.Errorf("monitor: wandb-symon binary not found: %v", err)
	}

	cmd := exec.Command(cmdPath, "--parent-pid", strconv.Itoa(os.Getpid()))
	if m.enableDCGMProfiling {
		cmd.Args = append(cmd.Args, "--enable-dcgm-profiling")
	}
	if !supportsUDS() {
		cmd.Args = append(cmd.Args, "--listen-on-localhost")
	}

	address := &addressLine{received: make(chan struct{})}
	cmd.Stdout = address
	stderr := &stderrTail{}
	cmd.Stderr = stderr
	cmd.WaitDelay = time.Second

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("monitor: could not start wandb-symon binary: %v", err)
	}
	exited := make(chan struct{})
	go func() {
		_ = cmd.Wait()
		close(exited)
	}()

	ctx, cancel := context.WithTimeout(ctx, collectorStartupTimeout)
	defer cancel()
	var targetURI string
	select {
	case <-address.received:
		targetURI, err = parseAddress(address.line())
	case <-exited:
		err = errors.New("wandb-symon exited before printing its address")
	case <-ctx.Done():
		err = fmt.Errorf("waiting for the wandb-symon address: %w", ctx.Err())
	}
	if err != nil {
		_ = cmd.Process.Kill()
		<-exited
		return fmt.Errorf(
			"monitor: wandb-symon binary failed to start: %w (%v, stderr: %q)",
			err,
			cmd.ProcessState,
			strings.TrimSpace(string(stderr.buf)),
		)
	}

	conn, err := grpc.NewClient(
		targetURI,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		_ = cmd.Process.Kill()
		<-exited
		return fmt.Errorf("monitor: could not connect to wandb-symon binary: %v", err)
	}

	m.collectorProcess = cmd
	m.collectorExited = exited
	m.collectorConn = conn
	m.collectorClient = spb.NewSystemMonitorServiceClient(conn)
	return nil
}

// symonPath returns the path to the wandb-symon sidecar binary.
func symonPath() (string, error) {
	ex, err := os.Executable()
	if err != nil {
		return "", err
	}
	dir := filepath.Dir(ex)

	p := filepath.Join(dir, "wandb-symon")
	if runtime.GOOS == "windows" {
		p += ".exe"
	}
	if _, err := os.Stat(p); err == nil {
		return p, nil
	}

	return "", fmt.Errorf("wandb-symon not found in %s", dir)
}

func supportsUDS() bool {
	if runtime.GOOS != "windows" {
		return true
	}

	tempDir, err := os.MkdirTemp("", "uds-support-check-*")
	if err != nil {
		return false
	}
	defer func() { _ = os.RemoveAll(tempDir) }()

	socketPath := filepath.Join(tempDir, "test.sock")
	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		return false
	}
	return listener.Close() == nil
}

// parseAddress converts the sidecar's address line, "unix=<path>" or
// "sock=<port>", to a gRPC target.
func parseAddress(line string) (string, error) {
	if path, found := strings.CutPrefix(line, "unix="); found {
		return "unix:" + path, nil
	}
	if portStr, found := strings.CutPrefix(line, "sock="); found {
		port, err := strconv.Atoi(portStr)
		if err != nil {
			return "", fmt.Errorf("invalid wandb-symon address %q: %v", line, err)
		}
		return fmt.Sprintf("127.0.0.1:%d", port), nil
	}
	return "", fmt.Errorf("unknown wandb-symon address %q", line)
}

// addressLine captures the first line written to it and closes received.
type addressLine struct {
	buf      []byte
	received chan struct{}
}

func (l *addressLine) Write(p []byte) (int, error) {
	select {
	case <-l.received:
	default:
		l.buf = append(l.buf, p...)
		if bytes.IndexByte(l.buf, '\n') >= 0 {
			close(l.received)
		}
	}
	return len(p), nil
}

func (l *addressLine) line() string {
	line, _, _ := strings.Cut(string(l.buf), "\n")
	return line
}

// stderrTail keeps the last stderrTailSize bytes written to it.
type stderrTail struct{ buf []byte }

func (t *stderrTail) Write(p []byte) (int, error) {
	t.buf = append(t.buf, p...)
	if n := len(t.buf) - stderrTailSize; n > 0 {
		t.buf = t.buf[n:]
	}
	return len(p), nil
}
