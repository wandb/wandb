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

type GPUResourceManagerRef int

// GPUResourceManager manages costly resources used for GPU metrics.
type GPUResourceManager struct {
	mu sync.Mutex

	// collectorProcess is the side process for reading GPU metrics.
	//
	// This is nil when connected to a shared collector that this instance
	// did not spawn. In that case, TearDown is not sent on Release.
	collectorProcess *exec.Cmd

	// collectorConn is the gRPC connection to the GPU collector process.
	collectorConn *grpc.ClientConn

	// collectorClient is the gRPC client for the SystemMonitorService.
	collectorClient spb.SystemMonitorServiceClient

	// refs is the set of users of the GPU collector process.
	//
	// The process is kept alive while this is nonempty. It is shut down when
	// this becomes empty.
	refs      map[GPUResourceManagerRef]struct{}
	nextRefId int

	// enableDCGMProfiling is true if collecting profiling metrics for
	// Nvidia GPUs using DCGM is requested.
	//
	// Enabling this feature can lead to increased resource usage compared to
	// standard monitoring with NVML.
	// Requires the `nvidia-dcgm` service to be running on the machine.
	// Note that this is a global per-collector-process flag.
	enableDCGMProfiling bool
}

// NewGPUResourceManager creates a GPUResourceManager.
func NewGPUResourceManager(enableDCGMProfiling bool) *GPUResourceManager {
	return &GPUResourceManager{
		refs:                map[GPUResourceManagerRef]struct{}{},
		enableDCGMProfiling: enableDCGMProfiling,
	}
}

// Acquire returns a gRPC client for the GPU monitoring process.
//
// The first call to Acquire starts (or connects to) the GPU stats process.
// Subsequent calls within the same instance reuse the existing connection.
//
// On Unix systems the manager first tries to connect to a shared GPU stats
// process shared across all wandb-core instances on the machine. If that
// fails it falls back to spawning a per-process collector.
//
// The returned reference ID must eventually be passed to Release.
func (m *GPUResourceManager) Acquire() (
	spb.SystemMonitorServiceClient,
	GPUResourceManagerRef,
	error,
) {
	m.mu.Lock()
	defer m.mu.Unlock()

	if m.collectorConn == nil {
		if err := m.connectCollector(); err != nil {
			return nil, 0, err
		}
	}

	refID := GPUResourceManagerRef(m.nextRefId)
	m.nextRefId++
	m.refs[refID] = struct{}{}
	return m.collectorClient, refID, nil
}

// connectCollector establishes a connection to a GPU stats collector.
//
// It first attempts to connect to a shared collector (Unix only), then falls
// back to spawning a per-process collector.
//
// Must be called with m.mu held.
func (m *GPUResourceManager) connectCollector() error {
	// On Unix, try the shared collector first. A shared collector is a single
	// gpu_stats process that all wandb-core instances on the machine connect
	// to, avoiding redundant per-process collectors.
	//
	// cmdPath is looked up after the fast-path connect attempt so that a
	// missing binary doesn't prevent connecting to an already-running collector
	// (e.g. one started by a different wandb installation).
	if supportsUDS() {
		cmdPath, _ := getGPUCollectorCmdPath() // empty string disables start-if-missing
		conn, err := connectOrStartSharedCollector(cmdPath, m.enableDCGMProfiling)
		if err == nil {
			// Connected to shared collector. collectorProcess stays nil
			// because we do NOT own the lifecycle of this process.
			m.collectorConn = conn
			m.collectorClient = spb.NewSystemMonitorServiceClient(conn)
			return nil
		}
		// Shared mode failed; fall through to per-process mode.
	}

	// Per-process fallback: spawn a dedicated gpu_stats for this wandb-core.
	cmdPath, err := getGPUCollectorCmdPath()
	if err != nil {
		return fmt.Errorf("monitor: could not find GPU binary: %v", err)
	}
	return m.startGPUCollector(cmdPath)
}

// Release marks the reference unused.
//
// Releasing the same ref twice is a no-op.
//
// If the reference count hits zero and this instance owns the collector
// process (i.e. it was started in per-process mode), the process is shut down.
// Shared-mode connections are simply closed; the shared collector manages
// its own lifetime.
func (m *GPUResourceManager) Release(ref GPUResourceManagerRef) {
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
		if proc != nil {
			// We own this process; request a clean shutdown.
			// Errors are ignored: we shut down on a best-effort basis.
			_, _ = client.TearDown(context.Background(), &spb.TearDownRequest{})
		}
		_ = conn.Close()
		if proc != nil {
			// NOTE: This may block indefinitely if the process fails to exit.
			_ = proc.Wait()
		}
	}()
}

// startGPUCollector spawns a per-process gpu_stats binary and connects to it.
//
// Must be called with m.mu held.
func (m *GPUResourceManager) startGPUCollector(cmdPath string) error {
	pf := NewPortfile()
	if pf == nil {
		return errors.New("monitor: could not create portfile")
	}
	defer func() { _ = pf.Delete() }()

	args := []string{
		"--portfile", pf.Path,
		"--parent-pid", strconv.Itoa(os.Getpid()),
	}
	if m.enableDCGMProfiling {
		args = append(args, "--enable-dcgm-profiling")
	}
	if !supportsUDS() {
		args = append(args, "--listen-on-localhost")
	}

	cmd := exec.Command(cmdPath, args...)
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("monitor: could not start GPU binary: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	targetURI, err := pf.Read(ctx)
	if err != nil {
		_ = cmd.Process.Kill()
		return fmt.Errorf("monitor: could not get GPU binary port: %v", err)
	}

	conn, err := grpc.NewClient(
		targetURI,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		_ = cmd.Process.Kill()
		return fmt.Errorf("monitor: could not make gRPC connection to GPU binary: %v", err)
	}

	m.collectorProcess = cmd
	m.collectorConn = conn
	m.collectorClient = spb.NewSystemMonitorServiceClient(conn)
	return nil
}

// getGPUCollectorCmdPath returns the path to the gpu_stats binary.
func getGPUCollectorCmdPath() (string, error) {
	ex, err := os.Executable()
	if err != nil {
		return "", err
	}
	exDirPath := filepath.Dir(ex)
	exPath := filepath.Join(exDirPath, "gpu_stats")

	// append .exe if running on Windows
	if runtime.GOOS == "windows" {
		exPath += ".exe"
	}

	if _, err := os.Stat(exPath); os.IsNotExist(err) {
		return "", err
	}
	return exPath, nil
}

// supportUDS performs a runtime check for Unix Domain Socket support.
//
// On non-Windows systems supported by W&B, it assumes that UDS is supported.
// On Windows, it attempts to create a temporary UDS listener to verify support.
func supportsUDS() bool {
	if runtime.GOOS != "windows" {
		return true
	}

	tempDir, err := os.MkdirTemp("", "uds-support-check-*")
	if err != nil {
		return false
	}
	defer func() {
		_ = os.RemoveAll(tempDir)
	}()

	socketPath := filepath.Join(tempDir, "test.sock")

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		return false
	}
	if err = listener.Close(); err != nil {
		return false
	}

	return true
}
