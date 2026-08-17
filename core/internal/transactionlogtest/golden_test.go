package transactionlogtest

import (
	"bytes"
	"flag"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/encoding/prototext"

	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var updateGoldenLogs = flag.Bool(
	"update-golden-logs",
	false,
	"regenerate tests/assets/compat_logs from goldenCorpus instead of"+
		" checking that it's up to date",
)

// goldenCorpusCase is defines an entry in the set of synthetic fixtures under
// tests/assets/compat_logs.
type goldenCorpusCase struct {
	// Name is the fixture name and the run ID used in its records.
	Name string

	// Records are the file's records, in order, as Record prototext.
	Records []string
}

// goldenCorpus is the source of truth for the set of synthetic fixtures under
// tests/assets/compat_logs.
//
// Each entry represents a .wandb transaction log written by a specific SDK
// version. Assume by default that the fixture is correct. Do not edit these
// fixtures unless you have reason to believe the fixture is incorrect.
//
// "old_" fixtures represent the on-disk shape before wandb PR #12110 (merge
// base 4f92599d0), where HistoryRecord have both `step` and `"_step"` fields,
// and the accompanying SummaryRecord has `"_step"` too.
//
// "new_" fixtures represent the shape after that PR, where auto-step rows
// carry none of the three because steps are assigned downstream by
// HistoryStepTracker in the Sender.
//
// If you must edit this table, regenerate the fixtures with:
//
//	go test ./internal/transactionlogtest -update-golden-logs
//
// then review the diff.
var goldenCorpus = []goldenCorpusCase{
	{
		// Old log with auto-assigned steps, using nested-key "_step"
		Name: "old_auto_steps",
		Records: []string{
			`run { run_id: "old_auto_steps" }`,
			`summary { update { nested_key: "_step" value_json: "0" } }`,
			`history {
				step { num: 0 }
				item { nested_key: "x" value_json: "0" }
				item { nested_key: "_step" value_json: "0" }
			}`,
			`summary { update { nested_key: "_step" value_json: "1" } }`,
			`history {
				step { num: 1 }
				item { nested_key: "x" value_json: "1" }
				item { nested_key: "_step" value_json: "1" }
			}`,
			`summary { update { nested_key: "_step" value_json: "2" } }`,
			`history {
				step { num: 2 }
				item { nested_key: "x" value_json: "2" }
				item { nested_key: "_step" value_json: "2" }
			}`,
			`exit { exit_code: 0 }`,
		},
	},
	{
		// Old log with auto-assigned steps, using flat key "_step"
		// (pre-Go-core Python sender)
		Name: "old_auto_steps_flat_keys",
		Records: []string{
			`run { run_id: "old_auto_steps_flat_keys" }`,
			`summary { update { key: "_step" value_json: "0" } }`,
			`history {
				step { num: 0 }
				item { key: "x" value_json: "0" }
				item { key: "_step" value_json: "0" }
			}`,
			`summary { update { key: "_step" value_json: "1" } }`,
			`history {
				step { num: 1 }
				item { key: "x" value_json: "1" }
				item { key: "_step" value_json: "1" }
			}`,
			`summary { update { key: "_step" value_json: "2" } }`,
			`history {
				step { num: 2 }
				item { key: "x" value_json: "2" }
				item { key: "_step" value_json: "2" }
			}`,
			`exit { exit_code: 0 }`,
		},
	},
	{
		// Old log with user-supplied explicit steps.
		Name: "old_explicit_steps",
		Records: []string{
			`run { run_id: "old_explicit_steps" }`,
			`summary { update { nested_key: "_step" value_json: "0" } }`,
			`history {
				step { num: 0 }
				item { nested_key: "x" value_json: "0" }
				item { nested_key: "_step" value_json: "0" }
			}`,
			`summary { update { nested_key: "_step" value_json: "5" } }`,
			`history {
				step { num: 5 }
				item { nested_key: "x" value_json: "1" }
				item { nested_key: "_step" value_json: "5" }
			}`,
			`summary { update { nested_key: "_step" value_json: "10" } }`,
			`history {
				step { num: 10 }
				item { nested_key: "x" value_json: "2" }
				item { nested_key: "_step" value_json: "10" }
			}`,
			`exit { exit_code: 0 }`,
		},
	},
	{
		// A shared-mode run has no step data in either version.
		Name: "old_shared_mode",
		Records: []string{
			`run { run_id: "old_shared_mode" }`,
			`history { item { nested_key: "x" value_json: "0" } }`,
			`history { item { nested_key: "x" value_json: "1" } }`,
			`exit { exit_code: 0 }`,
		},
	},
	{
		// A log with no history records at all. Should not assert anything
		// about steps.
		Name: "old_no_history",
		Records: []string{
			`run { run_id: "old_no_history" }`,
			`summary { update { nested_key: "score" value_json: "1.0" } }`,
			`exit { exit_code: 0 }`,
		},
	},
	{
		// An online-resumed run, with a starting step. The starting step
		// must not be renumbered or warned about.
		Name: "old_resumed_run",
		Records: []string{
			`run { run_id: "old_resumed_run" starting_step: 5 resumed: true }`,
			`summary { update { nested_key: "_step" value_json: "5" } }`,
			`history {
				step { num: 5 }
				item { nested_key: "x" value_json: "0" }
				item { nested_key: "_step" value_json: "5" }
			}`,
			`summary { update { nested_key: "_step" value_json: "6" } }`,
			`history {
				step { num: 6 }
				item { nested_key: "x" value_json: "1" }
				item { nested_key: "_step" value_json: "6" }
			}`,
			`summary { update { nested_key: "_step" value_json: "7" } }`,
			`history {
				step { num: 7 }
				item { nested_key: "x" value_json: "2" }
				item { nested_key: "_step" value_json: "7" }
			}`,
			`exit { exit_code: 0 }`,
		},
	},
	{
		// A shared-mode log with invalid step values. A user's explicit _step
		// value is passed through without type validation, so it can contain any JSON value.
		Name: "old_bad_step_types",
		Records: []string{
			`run { run_id: "old_bad_step_types" }`,
			`history { item { nested_key: "_step" value_json: "\"5\"" } }`,
			`history { item { nested_key: "_step" value_json: "5.5" } }`,
			`history { item { nested_key: "_step" value_json: "null" } }`,
			`history { item { nested_key: "_step" value_json: "true" } }`,
			`history { item { nested_key: "_step" value_json: "{\"a\":1}" } }`,
			`history { item { nested_key: "_step" value_json: "[1]" } }`,
			`exit { exit_code: 0 }`,
		},
	},
	{
		// Same as "old_auto_steps", but in the new format without step data.
		Name: "new_auto_steps",
		Records: []string{
			`run { run_id: "new_auto_steps" }`,
			`history { item { nested_key: "x" value_json: "0" } }`,
			`history { item { nested_key: "x" value_json: "1" } }`,
			`history { item { nested_key: "x" value_json: "2" } }`,
			`summary { update { nested_key: "x" value_json: "2" } }`,
			`exit { exit_code: 0 }`,
		},
	},
	{
		// Same as "old_explicit_steps", but in the new format; explicit steps
		// still write record.Step and summary._step, but no _step item.
		Name: "new_explicit_steps",
		Records: []string{
			`run { run_id: "new_explicit_steps" }`,
			`summary { update { nested_key: "_step" value_json: "0" } }`,
			`history { step { num: 0 } item { nested_key: "x" value_json: "0" } }`,
			`summary { update { nested_key: "_step" value_json: "5" } }`,
			`history { step { num: 5 } item { nested_key: "x" value_json: "1" } }`,
			`summary { update { nested_key: "_step" value_json: "10" } }`,
			`history { step { num: 10 } item { nested_key: "x" value_json: "2" } }`,
			`exit { exit_code: 0 }`,
		},
	},
	{
		// Same as "old_shared_mode"; the new format does not change anything.
		Name: "new_shared_mode",
		Records: []string{
			`run { run_id: "new_shared_mode" }`,
			`history { item { nested_key: "x" value_json: "0" } }`,
			`history { item { nested_key: "x" value_json: "1" } }`,
			`exit { exit_code: 0 }`,
		},
	},
	{
		// A new-format log recorded with resume mode set.
		Name: "new_resume_mode",
		Records: []string{
			`run { run_id: "new_resume_mode" resume_mode: true }`,
			`history { item { nested_key: "x" value_json: "0" } }`,
			`history { item { nested_key: "x" value_json: "1" } }`,
			`history { item { nested_key: "x" value_json: "2" } }`,
			`exit { exit_code: 0 }`,
		},
	},
}

// TestGoldenLogs_UpToDate defaults to checkint that the committed fixtures are
// up to date. It can be overridden with the -update-golden-logs flag to
// regenerate the fixtures. Failure may be due to changing the goldenCorpus
// entries, or a bug in the test code.
func TestGoldenLogs_UpToDate(t *testing.T) {
	generatedDir := t.TempDir()
	for _, c := range goldenCorpus {
		writeGoldenCase(t, goldenLogPath(generatedDir, c.Name), c)
	}

	if *updateGoldenLogs {
		for _, c := range goldenCorpus {
			dst := goldenLogPath(goldenLogDir(), c.Name)
			require.NoError(t, os.MkdirAll(filepath.Dir(dst), 0o777))
			copyFile(t,
				goldenLogPath(generatedDir, c.Name),
				dst)
		}
		t.Skip("regenerated tests/assets/compat_logs;" +
			" re-run without -update-golden-logs to verify")
	}

	for _, c := range goldenCorpus {
		generated, err := os.ReadFile(
			goldenLogPath(generatedDir, c.Name))
		require.NoError(t, err)

		committed, err := os.ReadFile(goldenLogPath(goldenLogDir(), c.Name))
		if err != nil {
			t.Errorf(
				"%s: committed golden log is missing or unreadable (%v);"+
					" run `go test ./internal/transactionlogtest"+
					" -update-golden-logs` to generate it",
				c.Name, err)
			continue
		}

		if !bytes.Equal(generated, committed) {
			t.Errorf(
				"%s: committed golden log does not match goldenCorpus;"+
					" run `go test ./internal/transactionlogtest"+
					" -update-golden-logs` to regenerate it, then review"+
					" the diff",
				c.Name)
		}
	}

	corpusNames := make(map[string]struct{}, len(goldenCorpus))
	for _, c := range goldenCorpus {
		corpusNames[c.Name] = struct{}{}
	}
	err := filepath.WalkDir(goldenLogDir(), func(path string, d fs.DirEntry, err error) error {
		require.NoError(t, err)
		if d.IsDir() {
			return nil
		}
		if !strings.HasSuffix(path, ".wandb") {
			return nil
		}

		rel, err := filepath.Rel(goldenLogDir(), path)
		require.NoError(t, err)
		if strings.HasPrefix(rel, "provenance"+string(filepath.Separator)) {
			return nil
		}

		dir := filepath.Dir(rel)
		if !strings.HasPrefix(dir, "offline-run-") {
			t.Errorf("unexpected .wandb file outside offline-run-*: %s", rel)
			return nil
		}
		name := strings.TrimPrefix(dir, "offline-run-")
		if _, ok := corpusNames[name]; !ok {
			t.Errorf(
				"%s: committed fixture has no goldenCorpus entry; add one or"+
					" delete the orphaned file",
				rel)
		}
		return nil
	})
	require.NoError(t, err)
}

// writeGoldenCase writes a case's records to a .wandb file at path,
// creating parent directories as needed.
func writeGoldenCase(t *testing.T, path string, c goldenCorpusCase) {
	t.Helper()
	require.NoError(t, os.MkdirAll(filepath.Dir(path), 0o777))

	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)

	for _, txtpb := range c.Records {
		var rec spb.Record
		require.NoErrorf(t, prototext.Unmarshal([]byte(txtpb), &rec),
			"%s: invalid record prototext: %s", c.Name, txtpb)
		require.NoError(t, w.Write(&rec))
	}

	require.NoError(t, w.Close())
}

func copyFile(t *testing.T, src, dst string) {
	t.Helper()

	contents, err := os.ReadFile(src)
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(dst, contents, 0o666))
}
