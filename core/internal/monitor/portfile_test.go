package monitor_test

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/wandb/wandb/core/internal/monitor"
)

func writeToTempFile(t *testing.T, path, content string) {
	t.Helper()
	err := os.WriteFile(path, []byte(content), 0644)
	if err != nil {
		t.Fatalf("Failed to write to temp file: %v", err)
	}
}

func TestReadFile(t *testing.T) {
	testCases := []struct {
		name           string
		fileContent    string
		expected       string
		expectErr      bool
		expectedErrMsg string
	}{
		{
			name:        "Valid TCP Port",
			fileContent: "sock=12345\n",
			expected:    "127.0.0.1:12345",
			expectErr:   false,
		},
		{
			name:        "Valid Unix Socket",
			fileContent: "unix=/tmp/test.sock",
			expected:    "unix:/tmp/test.sock",
			expectErr:   false,
		},
		{
			name:        "Valid Unix Socket with Windows Path",
			fileContent: `unix=C:\Users\test\wandb.sock`,
			expected:    `unix:C:\Users\test\wandb.sock`,
			expectErr:   false,
		},
		{
			name:           "Empty File",
			fileContent:    "",
			expectErr:      true,
			expectedErrMsg: "portfile is empty",
		},
		{
			name:           "Unknown Format",
			fileContent:    "invalid_format=999",
			expectErr:      true,
			expectedErrMsg: "unknown format in portfile",
		},
		{
			name:           "Malformed TCP Port",
			fileContent:    "sock=not-a-number",
			expectErr:      true,
			expectedErrMsg: "invalid port in portfile",
		},
		{
			name:           "File with only newline",
			fileContent:    "\n",
			expectErr:      true,
			expectedErrMsg: "unknown format in portfile",
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			pf := monitor.NewPortfile()
			writeToTempFile(t, pf.Path, tc.fileContent)

			target, err := pf.ReadFile()

			if tc.expectErr {
				if err == nil {
					t.Fatal("Expected an error, but got nil")
				}
				if !strings.Contains(err.Error(), tc.expectedErrMsg) {
					t.Errorf("Expected error message to contain %q, but got %q", tc.expectedErrMsg, err.Error())
				}
			} else {
				if err != nil {
					t.Fatalf("Expected no error, but got: %v", err)
				}
				if target != tc.expected {
					t.Errorf("Expected target %q, but got %q", tc.expected, target)
				}
			}
		})
	}

	t.Run("File Does Not Exist", func(t *testing.T) {
		pf := monitor.NewPortfile()
		pf.Path = filepath.Join(t.TempDir(), "nonexistent.file")
		_, err := pf.ReadFile()
		if err == nil {
			t.Fatal("Expected an error for a non-existent file, but got nil")
		}
		if !os.IsNotExist(err) {
			t.Errorf("Expected a file-not-exist error, but got a different error: %v", err)
		}
	})
}

func TestRead_SuccessWithPolling(t *testing.T) {
	pf := monitor.NewPortfile()
	defer func() { _ = pf.Delete() }()

	expectedTarget := "127.0.0.1:54321"
	fileContent := "sock=54321"
	go func() {
		time.Sleep(200 * time.Millisecond)
		err := os.WriteFile(pf.Path, []byte(fileContent), 0644)
		if err != nil {
			// Use t.Error in a goroutine as t.Fatal will not stop the test.
			t.Errorf("Failed to write to portfile in goroutine: %v", err)
		}
	}()

	// Use a context with a timeout that is longer than the write delay.
	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()

	// This should block, poll, and eventually succeed.
	target, err := pf.Read(ctx)

	if err != nil {
		t.Fatalf("Read() failed: %v", err)
	}

	if target != expectedTarget {
		t.Errorf("Expected target %q, got %q", expectedTarget, target)
	}
}
