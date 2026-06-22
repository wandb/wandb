//go:build unix

package listeners

import (
	"bytes"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestUnixSocketListener_CloseRemovesDir(t *testing.T) {
	var portInfo PortInfo

	listener, err := listenInTempDir("wandb-test-*", &portInfo)
	if err != nil {
		t.Fatalf("listenInTempDir() returned error: %v", err)
	}

	sockDir := filepath.Dir(portInfo.UnixPath)
	if err := listener.Close(); err != nil {
		t.Fatalf("Close() returned error: %v", err)
	}

	if _, err := os.Stat(sockDir); !os.IsNotExist(err) {
		t.Fatalf("Stat(sockDir) after Close = %v, want not exist", err)
	}
}

func TestListenUnix_RemovesDirOnListenFailure(t *testing.T) {
	sockDir, err := os.MkdirTemp(t.TempDir(), "wandb-test-")
	if err != nil {
		t.Fatalf("MkdirTemp() returned error: %v", err)
	}

	socketPath := filepath.Join(sockDir, "socket")
	if err := os.WriteFile(socketPath, nil, 0o600); err != nil {
		t.Fatalf("WriteFile() returned error: %v", err)
	}

	var portInfo PortInfo
	if _, err := listenUnix(sockDir, socketPath, &portInfo); err == nil {
		t.Fatal("listenUnix() succeeded, want error")
	}

	if _, err := os.Stat(sockDir); !os.IsNotExist(err) {
		t.Fatalf("Stat(sockDir) after failed listen = %v, want not exist", err)
	}
}

func TestMakeListeners_CloseRemovesUnixSocketDir(t *testing.T) {
	listenerList, portInfo, err := Config{ParentPID: os.Getpid()}.MakeListeners()
	if err != nil {
		t.Fatalf("MakeListeners() returned error: %v", err)
	}
	if portInfo.UnixPath == "" {
		t.Fatal("portInfo.UnixPath is empty, want Unix socket path")
	}
	if !strings.HasSuffix(portInfo.UnixPath, string(filepath.Separator)+"socket") {
		t.Fatalf("portInfo.UnixPath = %q, want suffix /socket", portInfo.UnixPath)
	}

	sockDir := filepath.Dir(portInfo.UnixPath)
	for _, listener := range listenerList {
		if err := listener.Close(); err != nil {
			t.Fatalf("Close() returned error: %v", err)
		}
	}

	if _, err := os.Stat(sockDir); !os.IsNotExist(err) {
		t.Fatalf("Stat(sockDir) after Close = %v, want not exist", err)
	}
}

func TestListenInTmp_CloseRemovesDir(t *testing.T) {
	if _, err := os.Stat("/tmp"); err != nil {
		t.Skip("/tmp is not available")
	}

	var portInfo PortInfo
	listener, err := listenInTmp("wandb-test-*", &portInfo)
	if err != nil {
		t.Fatalf("listenInTmp() returned error: %v", err)
	}

	sockDir := filepath.Dir(portInfo.UnixPath)
	if filepath.Dir(sockDir) != filepath.Clean("/tmp") {
		t.Fatalf("sockDir parent = %q, want /tmp", filepath.Dir(sockDir))
	}
	if !strings.HasPrefix(filepath.Base(sockDir), "wandb-test-") {
		t.Fatalf("sockDir base = %q, want wandb-test- prefix", filepath.Base(sockDir))
	}

	if err := listener.Close(); err != nil {
		t.Fatalf("Close() returned error: %v", err)
	}

	if _, err := os.Stat(sockDir); !os.IsNotExist(err) {
		t.Fatalf("Stat(sockDir) after Close = %v, want not exist", err)
	}
}

func TestMakeUnixListener_SetsPortInfoUnixPath(t *testing.T) {
	var portInfo PortInfo
	listener, err := makeUnixListener(os.Getpid(), &portInfo)
	if err != nil {
		t.Fatalf("makeUnixListener() returned error: %v", err)
	}
	t.Cleanup(func() { _ = listener.Close() })

	sockDir := filepath.Dir(portInfo.UnixPath)
	wantPath := filepath.Join(sockDir, "socket")
	if portInfo.UnixPath != wantPath {
		t.Fatalf("portInfo.UnixPath = %q, want %q", portInfo.UnixPath, wantPath)
	}

	if err := listener.Close(); err != nil {
		t.Fatalf("Close() returned error: %v", err)
	}

	if _, err := os.Stat(sockDir); !os.IsNotExist(err) {
		t.Fatalf("Stat(sockDir) after Close = %v, want not exist", err)
	}
}

func TestUnixSocketListener_CloseLogsWhenRemoveAllFails(t *testing.T) {
	var logs bytes.Buffer
	prevLogger := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{})))
	t.Cleanup(func() { slog.SetDefault(prevLogger) })

	var portInfo PortInfo
	listener, err := listenInTempDir("wandb-test-*", &portInfo)
	if err != nil {
		t.Fatalf("listenInTempDir() returned error: %v", err)
	}

	sockDir := filepath.Dir(portInfo.UnixPath)
	t.Cleanup(func() {
		_ = os.Chmod(sockDir, 0o700)
		_ = os.RemoveAll(sockDir)
	})

	if err := os.Chmod(sockDir, 0o500); err != nil {
		t.Fatalf("Chmod() returned error: %v", err)
	}

	_ = listener.Close()

	if _, err := os.Stat(sockDir); err != nil {
		t.Fatalf("Stat(sockDir) after failed cleanup = %v, want dir to remain", err)
	}

	logText := logs.String()
	if !strings.Contains(logText, "failed to remove Unix socket directory") {
		t.Fatalf("logs = %q, want removal failure warning", logText)
	}
	if !strings.Contains(logText, sockDir) {
		t.Fatalf("logs = %q, want dir %q", logText, sockDir)
	}
}

func TestUnixSocketListener_DoubleClose(t *testing.T) {
	var portInfo PortInfo
	listener, err := listenInTempDir("wandb-test-*", &portInfo)
	if err != nil {
		t.Fatalf("listenInTempDir() returned error: %v", err)
	}

	sockDir := filepath.Dir(portInfo.UnixPath)
	if err := listener.Close(); err != nil {
		t.Fatalf("first Close() returned error: %v", err)
	}

	if _, err := os.Stat(sockDir); !os.IsNotExist(err) {
		t.Fatalf("Stat(sockDir) after first Close = %v, want not exist", err)
	}

	// Second close may return an error but must not panic.
	_ = listener.Close()

	if _, err := os.Stat(sockDir); !os.IsNotExist(err) {
		t.Fatalf("Stat(sockDir) after second Close = %v, want not exist", err)
	}
}
