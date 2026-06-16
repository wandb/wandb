package listeners

import (
	"bytes"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func testLogger(t *testing.T) (*slog.Logger, *bytes.Buffer) {
	t.Helper()

	var logs bytes.Buffer
	return slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{})), &logs
}

func TestCleanupUnixSocketDir_EmptyPath(t *testing.T) {
	logger, logs := testLogger(t)

	cleanupUnixSocketDir("", logger)

	if logs.Len() != 0 {
		t.Fatalf("unexpected logs: %q", logs.String())
	}
}

func TestCleanupUnixSocketDir_RemovesDirUnderTempDir(t *testing.T) {
	logger, logs := testLogger(t)

	sockDir, err := os.MkdirTemp(os.TempDir(), "wandb-1-2-")
	if err != nil {
		t.Fatalf("MkdirTemp() returned error: %v", err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(sockDir) })

	socketPath := filepath.Join(sockDir, "socket")
	if err := os.WriteFile(socketPath, nil, 0o600); err != nil {
		t.Fatalf("WriteFile() returned error: %v", err)
	}

	cleanupUnixSocketDir(socketPath, logger)

	if _, err := os.Stat(sockDir); !os.IsNotExist(err) {
		t.Fatalf("Stat(sockDir) after cleanup = %v, want not exist", err)
	}
	if logs.Len() != 0 {
		t.Fatalf("unexpected logs: %q", logs.String())
	}
}

func TestCleanupUnixSocketDir_RemovesDirUnderTmp(t *testing.T) {
	if _, err := os.Stat("/tmp"); err != nil {
		t.Skip("/tmp is not available")
	}

	logger, logs := testLogger(t)

	sockDir, err := os.MkdirTemp("/tmp", "wandb-1-2-")
	if err != nil {
		t.Fatalf("MkdirTemp() returned error: %v", err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(sockDir) })

	socketPath := filepath.Join(sockDir, "socket")
	if err := os.WriteFile(socketPath, nil, 0o600); err != nil {
		t.Fatalf("WriteFile() returned error: %v", err)
	}

	cleanupUnixSocketDir(socketPath, logger)

	if _, err := os.Stat(sockDir); !os.IsNotExist(err) {
		t.Fatalf("Stat(sockDir) after cleanup = %v, want not exist", err)
	}
	if logs.Len() != 0 {
		t.Fatalf("unexpected logs: %q", logs.String())
	}
}

func TestCleanupUnixSocketDir_RefusesUnexpectedDirName(t *testing.T) {
	logger, logs := testLogger(t)

	sockDir := filepath.Join(t.TempDir(), "not-wandb-1-2-abc")
	if err := os.Mkdir(sockDir, 0o700); err != nil {
		t.Fatalf("Mkdir() returned error: %v", err)
	}
	socketPath := filepath.Join(sockDir, "socket")

	cleanupUnixSocketDir(socketPath, logger)

	if _, err := os.Stat(sockDir); err != nil {
		t.Fatalf("Stat(sockDir) after cleanup = %v, want dir to remain", err)
	}

	logText := logs.String()
	slog.Info("logs", "logs", logText)
	if !strings.Contains(logText, "refusing to remove unexpected Unix socket directory") {
		t.Fatalf("logs = %q, want refusal warning", logText)
	}
	if !strings.Contains(logText, sockDir) {
		t.Fatalf("logs = %q, want dir %q", logText, sockDir)
	}
}

func TestCleanupUnixSocketDir_RefusesDirOutsideTempRoots(t *testing.T) {
	logger, logs := testLogger(t)

	parent := filepath.Join(t.TempDir(), "outside")
	if err := os.Mkdir(parent, 0o700); err != nil {
		t.Fatalf("Mkdir() returned error: %v", err)
	}
	sockDir := filepath.Join(parent, "wandb-1-2-abc")
	if err := os.Mkdir(sockDir, 0o700); err != nil {
		t.Fatalf("Mkdir() returned error: %v", err)
	}
	socketPath := filepath.Join(sockDir, "socket")

	cleanupUnixSocketDir(socketPath, logger)

	if _, err := os.Stat(sockDir); err != nil {
		t.Fatalf("Stat(sockDir) after cleanup = %v, want dir to remain", err)
	}

	logText := logs.String()
	if !strings.Contains(logText, "refusing to remove unexpected Unix socket directory") {
		t.Fatalf("logs = %q, want refusal warning", logText)
	}
}

func TestCleanupUnixSocketDir_LogsWhenRemoveAllFails(t *testing.T) {
	logger, logs := testLogger(t)

	sockDir, err := os.MkdirTemp(os.TempDir(), "wandb-1-2-")
	if err != nil {
		t.Fatalf("MkdirTemp() returned error: %v", err)
	}
	t.Cleanup(func() {
		_ = os.Chmod(sockDir, 0o700)
		_ = os.RemoveAll(sockDir)
	})

	socketPath := filepath.Join(sockDir, "socket")
	if err := os.WriteFile(socketPath, nil, 0o600); err != nil {
		t.Fatalf("WriteFile() returned error: %v", err)
	}

	// Remove write permission so RemoveAll cannot delete entries in sockDir.
	if err := os.Chmod(sockDir, 0o500); err != nil {
		t.Fatalf("Chmod() returned error: %v", err)
	}

	cleanupUnixSocketDir(socketPath, logger)

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
	if !strings.Contains(logText, "permission denied") {
		t.Fatalf("logs = %q, want permission denied error", logText)
	}
}

func TestIsWandbUnixSocketDir(t *testing.T) {
	tempDir := filepath.Clean(os.TempDir())
	slashTmpDir := filepath.Clean("/tmp")

	tests := []struct {
		name string
		dir  string
		want bool
	}{
		{
			name: "valid under temp dir",
			dir:  filepath.Join(tempDir, "wandb-1-2-abc"),
			want: true,
		},
		{
			name: "valid under /tmp",
			dir:  filepath.Join(slashTmpDir, "wandb-9-10-xyz"),
			want: true,
		},
		{
			name: "wrong name",
			dir:  filepath.Join(tempDir, "not-wandb-1-2-abc"),
			want: false,
		},
		{
			name: "valid name outside temp roots",
			dir:  filepath.Join(tempDir, "outside", "wandb-1-2-abc"),
			want: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := isWandbUnixSocketDir(tt.dir); got != tt.want {
				t.Fatalf("isWandbUnixSocketDir(%q) = %t, want %t", tt.dir, got, tt.want)
			}
		})
	}
}
