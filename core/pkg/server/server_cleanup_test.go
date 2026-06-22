//go:build unix

package server

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/wandb/wandb/core/pkg/server/listeners"
)

func TestCleanupListeners_RemovesUnixSocketDir(t *testing.T) {
	listenerList, portInfo, err := listeners.Config{ParentPID: os.Getpid()}.MakeListeners()
	if err != nil {
		t.Fatalf("MakeListeners() returned error: %v", err)
	}
	if portInfo.UnixPath == "" {
		t.Fatal("portInfo.UnixPath is empty, want Unix socket path")
	}

	sockDir := filepath.Dir(portInfo.UnixPath)
	cleanupListeners(listenerList)

	if _, err := os.Stat(sockDir); !os.IsNotExist(err) {
		t.Fatalf("Stat(sockDir) after cleanup = %v, want not exist", err)
	}
}

func TestServe_DeferCleansUpOnEarlyReturn(t *testing.T) {
	tempRoot := t.TempDir()
	t.Setenv("TMPDIR", tempRoot)

	portFile := filepath.Join(tempRoot, "missing", "port.txt")

	s := NewServer(ServerParams{
		ParentPID: 0,
		Detached:  true,
	})

	if err := s.Serve(portFile); err == nil {
		t.Fatal("Serve() succeeded, want error")
	}

	matches, err := filepath.Glob(filepath.Join(tempRoot, "wandb-*"))
	if err != nil {
		t.Fatalf("Glob() returned error: %v", err)
	}
	if len(matches) != 0 {
		t.Fatalf("wandb temp dirs after early Serve return = %v, want none", matches)
	}
}

func TestServe_StopCleansUpSocketDir(t *testing.T) {
	tempRoot := t.TempDir()
	t.Setenv("TMPDIR", tempRoot)

	portFile := filepath.Join(tempRoot, "port.txt")
	s := NewServer(ServerParams{
		ParentPID: 0,
		Detached:  true,
	})

	srvCh := make(chan error, 1)
	go func() { srvCh <- s.Serve(portFile) }()

	var unixPath string
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		data, err := os.ReadFile(portFile)
		if err == nil {
			for line := range strings.SplitSeq(string(data), "\n") {
				if after, ok := strings.CutPrefix(line, "unix="); ok {
					unixPath = after
					break
				}
			}
			if unixPath != "" {
				break
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	if unixPath == "" {
		t.Fatal("timed out waiting for Unix socket path in port file")
	}

	sockDir := filepath.Dir(unixPath)
	s.Stop()

	select {
	case err := <-srvCh:
		if !errors.Is(err, ErrForcedShutdown) {
			t.Fatalf("Serve() = %v, want ErrForcedShutdown", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for Serve() to return")
	}

	if _, err := os.Stat(sockDir); !os.IsNotExist(err) {
		t.Fatalf("Stat(sockDir) after Stop = %v, want not exist", err)
	}
}
