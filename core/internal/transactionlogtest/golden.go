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
//
// The Go module root is core/, so //go:embed cannot reach tests/assets/;
// resolve the path relative to this source file instead.
func goldenLogDir() string {
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		panic("transactionlogtest: could not determine source file path")
	}
	return filepath.Join(
		filepath.Dir(thisFile), "..", "..", "..", "tests", "assets", "compat_logs")
}

// goldenLogRelPath returns a golden fixture's path relative to whatever
// directory holds the corpus (either the committed tests/assets/compat_logs
// or a temp dir it's being regenerated into).
//
// The "offline-run-" directory prefix is load-bearing: it matches the
// precedent set by tests/assets/wandb/offline-run-*, and wandb sync's
// online/offline heuristic keys on that prefix alone (no timestamp needed).
func goldenLogRelPath(name string) string {
	return filepath.Join("offline-run-"+name, "run-"+name+".wandb")
}

// goldenLogPath returns the path a golden fixture named name should live at,
// regardless of whether it currently exists.
func goldenLogPath(name string) string {
	return filepath.Join(goldenLogDir(), goldenLogRelPath(name))
}

// GoldenLogPath returns the path to a committed golden .wandb fixture under
// tests/assets/compat_logs.
//
// Use this only for read-only access. Anything that syncs the log must use
// [CopyGoldenLog] instead: syncing writes .synced and .syncstate sidecars
// next to the file, which would otherwise mutate the committed corpus.
func GoldenLogPath(t *testing.T, name string) string {
	t.Helper()

	path := goldenLogPath(name)
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("transactionlogtest: no golden log named %q: %v", name, err)
	}
	return path
}

// CopyGoldenLog copies a committed golden .wandb fixture into a fresh
// t.TempDir() and returns the copy's path.
func CopyGoldenLog(t *testing.T, name string) string {
	t.Helper()

	contents, err := os.ReadFile(GoldenLogPath(t, name))
	require.NoError(t, err)

	dst := filepath.Join(t.TempDir(), "run-"+name+".wandb")
	require.NoError(t, os.WriteFile(dst, contents, 0o666))

	return dst
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
