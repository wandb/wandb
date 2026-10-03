//go:build !windows

package monitor

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"syscall"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// sharedCollectorRoot holds the socket directories of shared
	// collectors when XDG_RUNTIME_DIR is not set.
	sharedCollectorRoot = "/tmp"

	// sharedCollectorIdleTimeout is how long a shared collector runs
	// after its last subscriber leaves.
	sharedCollectorIdleTimeout = 10 * time.Minute

	// sharedCollectorLockTimeout bounds how long startSharedCollector
	// waits for the lock that elects the process starting the collector.
	sharedCollectorLockTimeout = 10 * time.Second
)

// startSharedCollector connects to the wandb-xpu shared by the user's
// processes on this machine, starting it if none accepts connections.
func (m *XPUResourceManager) startSharedCollector(ctx context.Context) error {
	cmdPath, err := getXPUCmdPath()
	if err != nil {
		return err
	}
	socket, err := m.sharedCollectorSocket(cmdPath)
	if err != nil {
		return err
	}

	if !probeSharedCollector(socket) {
		if err := m.electSharedCollector(ctx, cmdPath, socket); err != nil {
			return err
		}
	}

	conn, err := grpc.NewClient(
		"unix:"+socket,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		return err
	}

	m.sharedSocket = socket
	m.collectorConn = conn
	m.collectorClient = spb.NewSystemMonitorServiceClient(conn)
	return nil
}

// sharedCollectorSocket returns the socket path of the shared collector
// built from the binary at cmdPath with this manager's collector flags,
// creating the user's socket directory.
func (m *XPUResourceManager) sharedCollectorSocket(
	cmdPath string,
) (string, error) {
	if m.sharedID == "" {
		id, err := fileDigest(cmdPath)
		if err != nil {
			return "", err
		}
		m.sharedID = id
	}

	uid := os.Getuid()
	dir, err := sharedCollectorDir(os.Getenv("XDG_RUNTIME_DIR"), uid)
	if err != nil {
		dir, err = sharedCollectorDir(sharedCollectorRoot, uid)
	}
	if err != nil {
		return "", err
	}

	id := m.sharedID
	if m.enableDCGMProfiling {
		id += "-dcgm"
	}
	socket := filepath.Join(dir, id+".sock")
	if len(socket) > 100 {
		return "", fmt.Errorf("%s is too long for a socket path", socket)
	}
	return socket, nil
}

// sharedCollectorDir returns the user's socket directory under root,
// creating it if needed and requiring it to be private to the user.
func sharedCollectorDir(root string, uid int) (string, error) {
	if root == "" {
		return "", errors.New("no runtime directory")
	}
	dir := filepath.Join(root, "wandb-xpu-"+strconv.Itoa(uid))
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", err
	}
	info, err := os.Lstat(dir)
	if err != nil {
		return "", err
	}
	stat, _ := info.Sys().(*syscall.Stat_t)
	if !info.IsDir() || stat == nil || int(stat.Uid) != uid {
		return "", fmt.Errorf("%s is not a directory owned by uid %d", dir, uid)
	}
	if info.Mode().Perm()&0o077 != 0 {
		if err := os.Chmod(dir, 0o700); err != nil {
			return "", err
		}
	}
	return dir, nil
}

// electSharedCollector starts the shared collector on socket under the
// lock file beside it, unless another process did so first, and waits
// until it accepts connections.
func (m *XPUResourceManager) electSharedCollector(
	ctx context.Context,
	cmdPath string,
	socket string,
) error {
	unlock, err := lockSharedCollector(ctx, socket+".lock")
	if err != nil {
		return err
	}
	defer unlock()

	if probeSharedCollector(socket) {
		return nil
	}
	if err := os.Remove(socket); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}

	cmd := exec.Command(
		cmdPath,
		"--listen", socket,
		"--idle-timeout", strconv.Itoa(int(sharedCollectorIdleTimeout/time.Second)),
	)
	if m.enableDCGMProfiling {
		cmd.Args = append(cmd.Args, "--enable-dcgm-profiling")
	}
	cmd.Dir = "/"
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err := cmd.Start(); err != nil {
		return err
	}
	exited := make(chan struct{})
	go func() {
		_ = cmd.Wait()
		close(exited)
	}()

	ctx, cancel := context.WithTimeout(ctx, collectorStartupTimeout)
	defer cancel()
	for !probeSharedCollector(socket) {
		select {
		case <-ctx.Done():
			return fmt.Errorf(
				"wandb-xpu does not accept connections on %s: %w",
				socket, ctx.Err(),
			)
		case <-exited:
			if probeSharedCollector(socket) {
				return nil
			}
			return fmt.Errorf("wandb-xpu exited before accepting connections on %s", socket)
		case <-time.After(10 * time.Millisecond):
		}
	}
	return nil
}

// lockSharedCollector takes an exclusive flock on the file at path and
// returns the function that releases it. It gives up when ctx ends or
// after sharedCollectorLockTimeout.
func lockSharedCollector(
	ctx context.Context,
	path string,
) (func(), error) {
	f, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE, 0o600)
	if err != nil {
		return nil, err
	}
	locked := make(chan error, 1)
	go func() { locked <- syscall.Flock(int(f.Fd()), syscall.LOCK_EX) }()

	ctx, cancel := context.WithTimeout(ctx, sharedCollectorLockTimeout)
	defer cancel()
	select {
	case err := <-locked:
		if err != nil {
			_ = f.Close()
			return nil, err
		}
		return func() { _ = f.Close() }, nil
	case <-ctx.Done():
		go func() {
			<-locked
			_ = f.Close()
		}()
		return nil, fmt.Errorf("waiting for %s: %w", path, ctx.Err())
	}
}

// fileDigest returns the first 16 hex digits of the SHA-256 of the file
// at path.
func fileDigest(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer func() { _ = f.Close() }()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil))[:16], nil
}
