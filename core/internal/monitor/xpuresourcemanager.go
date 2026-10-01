package monitor

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"sync"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// collectorStartupTimeout bounds how long Client waits for the
	// sidecar process to write its portfile.
	collectorStartupTimeout = 5 * time.Second

	// collectorShutdownTimeout bounds how long Release waits for the
	// sidecar process to exit after asking it to tear down.
	collectorShutdownTimeout = 5 * time.Second

	// sharedCollectorProbeTimeout bounds one connection attempt to the
	// shared collector's socket.
	sharedCollectorProbeTimeout = 500 * time.Millisecond
)

type XPUResourceManagerRef int

// XPUResourceOptions says how a reference wants to reach wandb-xpu.
type XPUResourceOptions struct {
	// Shared asks for the collector shared by the user's processes on this
	// machine instead of a sidecar private to this process.
	Shared bool

	// Logger receives a debug message when the shared collector cannot be
	// reached and a private sidecar is started instead.
	Logger *observability.CoreLogger
}

// XPUResourceManager manages the wandb-xpu process: a sidecar private
// to this process, or the collector shared by the user's processes on
// this machine.
//
// The sidecar runs while at least one reference is held and is started
// again by the next Client call after it exits. The shared collector is
// joined, or started again, by the next Client call after it stops
// accepting connections.
type XPUResourceManager struct {
	mu sync.Mutex

	collectorProcess *exec.Cmd
	collectorConn    *grpc.ClientConn
	collectorClient  spb.SystemMonitorServiceClient

	// collectorExited is closed when collectorProcess exits.
	collectorExited chan struct{}

	// sharedSocket is the socket of the shared collector collectorConn
	// is connected to, or empty for a private sidecar.
	sharedSocket string

	// sharedID names the shared collector's socket after the wandb-xpu
	// binary it is built from. It is computed on first use.
	sharedID string

	refs      map[XPUResourceManagerRef]XPUResourceOptions
	nextRefId int

	enableDCGMProfiling bool
}

func NewXPUResourceManager(enableDCGMProfiling bool) *XPUResourceManager {
	return &XPUResourceManager{
		refs:                map[XPUResourceManagerRef]XPUResourceOptions{},
		enableDCGMProfiling: enableDCGMProfiling,
	}
}

// Acquire registers a reference to wandb-xpu.
//
// The options of the reference whose Client call starts wandb-xpu apply
// to every reference in this process until it is started again.
func (m *XPUResourceManager) Acquire(
	opts XPUResourceOptions,
) XPUResourceManagerRef {
	m.mu.Lock()
	defer m.mu.Unlock()

	refID := XPUResourceManagerRef(m.nextRefId)
	m.nextRefId++
	m.refs[refID] = opts
	return refID
}

// Client returns a client for the sidecar, starting it if it is not
// running. ctx bounds the start.
func (m *XPUResourceManager) Client(
	ctx context.Context,
	ref XPUResourceManagerRef,
) (spb.SystemMonitorServiceClient, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	opts, ok := m.refs[ref]
	if !ok {
		return nil, errors.New("monitor: xpu reference was released")
	}

	if m.sharedSocket != "" && !probeSharedCollector(m.sharedSocket) {
		m.disconnectSharedCollector()
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
		if err := m.startCollector(ctx, opts); err != nil {
			return nil, err
		}
	}
	return m.collectorClient, nil
}

func (m *XPUResourceManager) Release(ref XPUResourceManagerRef) {
	m.mu.Lock()
	defer m.mu.Unlock()

	delete(m.refs, ref)
	if len(m.refs) > 0 || m.collectorConn == nil {
		return
	}

	if m.sharedSocket != "" {
		m.disconnectSharedCollector()
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

func (m *XPUResourceManager) startCollector(
	ctx context.Context,
	opts XPUResourceOptions,
) error {
	if err := ctx.Err(); err != nil {
		return err
	}

	if opts.Shared {
		err := m.startSharedCollector(ctx)
		if err == nil {
			return nil
		}
		opts.Logger.Debug("monitor: starting a private wandb-xpu", "error", err)
	}

	pf := NewPortfile()
	if pf == nil {
		return errors.New("monitor: could not create portfile")
	}
	defer func() { _ = pf.Delete() }()

	cmdPath, err := getXPUCmdPath()
	if err != nil {
		return fmt.Errorf("monitor: wandb-xpu binary not found: %v", err)
	}

	cmd := exec.Command(
		cmdPath,
		"--portfile", pf.Path,
		"--parent-pid", strconv.Itoa(os.Getpid()),
	)
	if m.enableDCGMProfiling {
		cmd.Args = append(cmd.Args, "--enable-dcgm-profiling")
	}
	if !supportsUDS() {
		cmd.Args = append(cmd.Args, "--listen-on-localhost")
	}

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("monitor: could not start wandb-xpu binary: %v", err)
	}
	exited := make(chan struct{})
	go func() {
		_ = cmd.Wait()
		close(exited)
	}()

	ctx, cancel := context.WithTimeout(ctx, collectorStartupTimeout)
	defer cancel()
	targetURI, err := pf.Read(ctx, exited)
	if err != nil {
		_ = cmd.Process.Kill()
		<-exited
		return fmt.Errorf("monitor: wandb-xpu binary failed to start: %w", err)
	}

	conn, err := grpc.NewClient(
		targetURI,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		_ = cmd.Process.Kill()
		<-exited
		return fmt.Errorf("monitor: could not connect to wandb-xpu binary: %v", err)
	}

	m.collectorProcess = cmd
	m.collectorExited = exited
	m.collectorConn = conn
	m.collectorClient = spb.NewSystemMonitorServiceClient(conn)
	return nil
}

// probeSharedCollector reports whether something accepts connections
// on socket.
func probeSharedCollector(socket string) bool {
	conn, err := net.DialTimeout("unix", socket, sharedCollectorProbeTimeout)
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
}

// disconnectSharedCollector drops the connection to the shared collector.
func (m *XPUResourceManager) disconnectSharedCollector() {
	_ = m.collectorConn.Close()
	m.sharedSocket = ""
	m.collectorConn = nil
	m.collectorClient = nil
}

// getXPUCmdPath returns the path to the wandb-xpu sidecar binary.
func getXPUCmdPath() (string, error) {
	ex, err := os.Executable()
	if err != nil {
		return "", err
	}
	dir := filepath.Dir(ex)

	p := filepath.Join(dir, "wandb-xpu")
	if runtime.GOOS == "windows" {
		p += ".exe"
	}
	if _, err := os.Stat(p); err == nil {
		return p, nil
	}

	return "", fmt.Errorf("wandb-xpu found in %s", dir)
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
