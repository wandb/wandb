package monitor

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"sync"
	"time"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

type GPUResourceManagerRef int

// GPUResourceManager manages costly resources used for GPU metrics.
type GPUResourceManager struct {
	mu sync.Mutex

	// collectorProcess is the side process for reading GPU metrics.
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
// The first call to Acquire starts the process. The returned reference ID
// must eventually be passed to Release to free resources.
func (m *GPUResourceManager) Acquire() (
	spb.SystemMonitorServiceClient,
	GPUResourceManagerRef,
	error,
) {
	m.mu.Lock()
	defer m.mu.Unlock()

	if m.collectorConn == nil {
		err := m.startGPUCollector()
		if err != nil {
			return nil, 0, err
		}
	}

	refID := GPUResourceManagerRef(m.nextRefId)
	m.nextRefId++
	m.refs[refID] = struct{}{}
	return m.collectorClient, refID, nil
}

// Release marks the reference unused.
//
// Releasing the same ref twice is a no-op.
//
// If the reference count hits zero, it shuts down the GPU collector process.
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
		// We shut down the client on a best-effort basis.
		// Any errors are ignored.
		_, _ = client.TearDown(context.Background(), &spb.TearDownRequest{})
		_ = conn.Close()

		// NOTE: This may block indefinitely if the process fails to exit.
		_ = proc.Wait()
	}()
}

func (m *GPUResourceManager) startGPUCollector() error {
	pf := NewPortfile()
	if pf == nil {
		return errors.New("monitor: could not create portfile")
	}
	defer func() { _ = pf.Delete() }()

	cmdPath, err := getGPUCollectorCmdPath()
	if err != nil {
		return fmt.Errorf("monitor: could not get path to GPU binary: %v", err)
	}

	cmd := exec.Command(
		cmdPath,
		"--portfile", pf.path,
		"--ppid", strconv.Itoa(os.Getpid()),
	)

	if m.enableDCGMProfiling {
		cmd.Args = append(cmd.Args, "--enable-dcgm-profiling")
	}

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("monitor: could not start GPU binary: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	port, err := pf.Read(ctx)
	if err != nil {
		_ = cmd.Process.Kill()
		return fmt.Errorf("monitor: could not get GPU binary port: %v", err)
	}

	conn, err := grpc.NewClient(
		fmt.Sprintf("127.0.0.1:%d", port),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)

	if err != nil {
		_ = cmd.Process.Kill()
		return fmt.Errorf(
			"monitor: could not make gRPC connection to GPU binary: %v",
			err)
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
