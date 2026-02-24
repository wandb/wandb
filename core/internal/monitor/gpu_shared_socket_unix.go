//go:build !windows

package monitor

import (
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// gpuSharedSock returns the well-known per-user socket path for the shared
// GPU stats collector. The .lock suffix is used for leader election.
func gpuSharedSock() string {
	return filepath.Join(os.TempDir(), fmt.Sprintf("wandb-gpu-v1-%d.sock", os.Getuid()))
}

// connectOrStartSharedCollector connects to the shared gpu_stats process,
// starting it via leader election if it is not already running.
//
// Returns a gRPC connection that the caller does NOT own – do not send
// TearDown on Release; the shared process manages its own lifetime.
// Falls back to per-process mode by returning an error.
func connectOrStartSharedCollector(cmdPath string, enableDCGM bool) (*grpc.ClientConn, error) {
	sock := gpuSharedSock()

	// Fast path: already running.
	if conn, err := dialShared(sock); err == nil {
		return conn, nil
	}

	// Leader election: first caller to flock wins and starts the collector.
	// The lock is released when f closes (defer below), at which point
	// waiters can connect to the now-running collector.
	f, err := os.OpenFile(sock+".lock", os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, fmt.Errorf("monitor: gpu-stats lock: %v", err)
	}
	defer func() { _ = f.Close() }()

	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		if err != syscall.EWOULDBLOCK {
			// Unexpected flock failure (bad fd, permissions, etc.) – fall back
			// to per-process mode rather than waiting blindly.
			return nil, fmt.Errorf("monitor: flock gpu-stats lock: %v", err)
		}
		// EWOULDBLOCK: another process won the election; wait for it.
		return pollSocket(sock, 10*time.Second)
	}

	// Re-check after acquiring the lock: a previous leader may have already
	// started the collector between our failed dial and the flock call.
	if conn, err := dialShared(sock); err == nil {
		return conn, nil
	}

	if cmdPath == "" {
		// Binary not found; can't start a new collector.
		return nil, fmt.Errorf("monitor: gpu_stats binary not found")
	}

	_ = os.Remove(sock) // clear any stale socket file

	// Do NOT pass --parent-pid in shared mode. In per-process mode, gpu_stats
	// uses the parent PID to exit when its owner dies. In shared mode there is
	// no single owner – multiple wandb-core processes connect and disconnect
	// independently. Passing the leader's PID would cause gpu_stats to exit
	// when the first leader finishes, killing metrics for all other clients.
	// The idle timeout handles shutdown instead.
	args := []string{"--bind-socket", sock}
	if enableDCGM {
		args = append(args, "--enable-dcgm-profiling")
	}
	cmd := exec.Command(cmdPath, args...)
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("monitor: start shared gpu_stats: %v", err)
	}
	// Release disowns the process so the Go runtime doesn't hold a handle to
	// it. Without this, the process becomes a zombie when it exits because
	// nothing ever calls Wait(). The shared collector exits on its own via
	// idle timeout; we are not responsible for reaping it.
	_ = cmd.Process.Release()

	// Lock released when f closes at the end of this function.
	return pollSocket(sock, 5*time.Second)
}

// dialShared checks liveness with a raw dial before creating the gRPC client.
// grpc.NewClient connects lazily, so without this check it would return
// a "connected" client even if nothing is listening.
func dialShared(sock string) (*grpc.ClientConn, error) {
	c, err := net.DialTimeout("unix", sock, 300*time.Millisecond)
	if err != nil {
		return nil, err
	}
	_ = c.Close()
	return grpc.NewClient("unix:"+sock, grpc.WithTransportCredentials(insecure.NewCredentials()))
}

// pollSocket retries dialShared every 200ms until timeout.
func pollSocket(sock string, timeout time.Duration) (*grpc.ClientConn, error) {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if conn, err := dialShared(sock); err == nil {
			return conn, nil
		}
		time.Sleep(200 * time.Millisecond)
	}
	return nil, fmt.Errorf("monitor: gpu-stats socket not ready at %s", sock)
}
