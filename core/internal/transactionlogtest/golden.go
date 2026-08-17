package transactionlogtest

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// goldenLogDir returns the absolute path to tests/assets/compat_logs.
func goldenLogDir() string {
	// Use current file's location to find tests/assets/compat_logs.
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		panic("transactionlogtest: could not determine source file path")
	}
	return filepath.Join(
		filepath.Dir(thisFile), "..", "..", "..", "tests", "assets", "compat_logs")
}

// goldenLogPath returns the path to a golden fixture named `name` under `rootDir`.
func goldenLogPath(rootDir string, name string) string {
	return filepath.Join(rootDir, "offline-run-"+name, "run-"+name+".wandb")
}

// GoldenLogPath returns the path to a committed golden .wandb fixture under
// tests/assets/compat_logs.
func GoldenLogPath(t *testing.T, name string) string {
	t.Helper()

	path := goldenLogPath(goldenLogDir(), name)
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("transactionlogtest: no golden log named %q: %v", name, err)
	}
	return path
}

// GoldenLogRecords returns every record in a committed golden .wandb
// fixture, in the order they were written.
func GoldenLogRecords(t *testing.T, name string) []*spb.Record {
	t.Helper()

	r, err := transactionlog.OpenReader(
		GoldenLogPath(t, name), observabilitytest.NewTestLogger(t))
	require.NoError(t, err)
	defer r.Close()

	var records []*spb.Record
	for {
		record, err := r.Read()
		if err != nil {
			require.Truef(t, errors.Is(err, io.EOF),
				"transactionlogtest: error reading golden log %q: %v", name, err)
			break
		}
		records = append(records, record)
	}

	return records
}
