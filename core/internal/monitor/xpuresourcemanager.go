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

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type XPUResourceManagerRef int

// XPUResourceManager manages the sidecar process that collects
// GPU and TPU metrics.
type XPUResourceManager struct {
	mu sync.Mutex

	collectorProcess *exec.Cmd
	collectorConn    *grpc.ClientConn
	collectorClient  spb.SystemMonitorServiceClient

	refs      map[XPUResourceManagerRef]struct{}
	nextRefId int

	enableDCGMProfiling bool
}

func NewXPUResourceManager(enableDCGMProfiling bool) *XPUResourceManager {
	return &XPUResourceManager{
		refs:                map[XPUResourceManagerRef]struct{}{},
		enableDCGMProfiling: enableDCGMProfiling,
	}
}

func (m *XPUResourceManager) Acquire() (
	spb.SystemMonitorServiceClient,
	XPUResourceManagerRef,
	error,
) {
	m.mu.Lock()
	defer m.mu.Unlock()

	if m.collectorConn == nil {
		if err := m.startCollector(); err != nil {
			return nil, 0, err
		}
	}

	refID := XPUResourceManagerRef(m.nextRefId)
	m.nextRefId++
	m.refs[refID] = struct{}{}
	return m.collectorClient, refID, nil
}

func (m *XPUResourceManager) Release(ref XPUResourceManagerRef) {
	m.mu.Lock()
	defer m.mu.Unlock()

	delete(m.refs, ref)
	if len(m.refs) > 0 {
		return
	}

	proc := m.collectorProcess
	conn := m.collectorConn
	client := m.collectorClient
	m.collectorProcess = nil
	m.collectorConn = nil
	m.collectorClient = nil

	go func() {
		_, _ = client.TearDown(context.Background(), &spb.TearDownRequest{})
		_ = conn.Close()
		_ = proc.Wait()
	}()
}

func (m *XPUResourceManager) startCollector() error {
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

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	targetURI, err := pf.Read(ctx)
	if err != nil {
		_ = cmd.Process.Kill()
		return fmt.Errorf("monitor: wandb-xpu binary failed to start: %v", err)
	}

	conn, err := grpc.NewClient(
		targetURI,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		_ = cmd.Process.Kill()
		return fmt.Errorf("monitor: could not connect to wandb-xpu binary: %v", err)
	}

	m.collectorProcess = cmd
	m.collectorConn = conn
	m.collectorClient = spb.NewSystemMonitorServiceClient(conn)
	return nil
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
