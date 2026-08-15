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

// updateGoldenLogs regenerates the committed fixtures under
// tests/assets/compat_logs from goldenCorpus instead of checking them.
//
// Run: go test ./internal/transactionlogtest -update-golden-logs
var updateGoldenLogs = flag.Bool(
	"update-golden-logs",
	false,
	"regenerate tests/assets/compat_logs from goldenCorpus instead of"+
		" checking that it's up to date",
)

// goldenCorpusCase is one entry in goldenCorpus.
type goldenCorpusCase struct {
	// Name is both the case name and the run ID used in its records, so
	// that e.g. a Python system test can read
	// `snapshot.history(run_id="old_auto_steps")`.
	Name string

	// Records are the file's records, in order, as Record prototext.
	Records []string
}

// goldenCorpus is the source of truth for every synthesized fixture under
// tests/assets/compat_logs.
//
// Each entry is this repo's claim about exactly what a .wandb transaction
// log written by some client version/format looks like. Editing an entry
// changes that claim; it is not a knob to turn to make a failing
// compatibility test pass. If a test built on one of these fixtures starts
// failing, treat the fixture as right and the code as wrong unless you have
// a specific reason to believe otherwise.
//
// "old_" fixtures pin the on-disk shape from before wandb PR #12110
// (merge base 4f92599d0): every non-shared HistoryRecord carries the step
// both as `step` (a HistoryStep message) and as an item keyed "_step", and
// the accompanying SummaryRecord carries "_step" too. "new_" fixtures pin
// the shape after that PR: auto-step rows carry none of the three, and
// _step is assigned downstream by HistoryStepTracker in the Sender.
//
// After editing this table, run:
//
//	go test ./internal/transactionlogtest -update-golden-logs
//
// to regenerate tests/assets/compat_logs, then review the diff.
var goldenCorpus = []goldenCorpusCase{
	{
		// The common case: an old offline log with auto-assigned steps,
		// written with the nested-key _step + record.Step + summary._step
		// shape. The R1 happy path and the R7 format-change baseline.
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
		// The same logical run as old_auto_steps, but written by a
		// pre-Go-core Python sender: _step as a flat key, not a nested one.
		// The PR's own tests never exercise this shape.
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
		// Sparse, user-supplied explicit steps. Pins R4's sparse-step
		// reasoning and the leet x-axis parity check.
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
		// A shared-mode run: no _step and no step in either era, since
		// shared mode never assigns one. Must stay untouched by the format
		// change; see new_shared_mode.
		Name: "old_shared_mode",
		Records: []string{
			`run { run_id: "old_shared_mode" }`,
			`history { item { nested_key: "x" value_json: "0" } }`,
			`history { item { nested_key: "x" value_json: "1" } }`,
			`exit { exit_code: 0 }`,
		},
	},
	{
		// The tests/assets/wandb/...g9dvvkua shape: a log with no history
		// records at all. Must sync without error and without asserting
		// anything about steps.
		Name: "old_no_history",
		Records: []string{
			`run { run_id: "old_no_history" }`,
			`summary { update { nested_key: "score" value_json: "1.0" } }`,
			`exit { exit_code: 0 }`,
		},
	},
	{
		// An online-resumed run: the log already starts at the resumed
		// starting step and must not be renumbered or warned about.
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
		// A shared-mode log passes a user's explicit _step straight through
		// with no type validation, so it can contain any JSON value.
		// Pins R3 for both the Go and Python readers.
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
		// The same logical run as old_auto_steps in the new format: auto
		// rows carry none of _step/step/summary._step. Pins R7.
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
		// The same logical run as old_explicit_steps in the new format: an
		// explicit step still writes record.Step and summary._step, but no
		// _step item.
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
		// Same shape as old_shared_mode: shared mode is unchanged by the
		// format change.
		Name: "new_shared_mode",
		Records: []string{
			`run { run_id: "new_shared_mode" }`,
			`history { item { nested_key: "x" value_json: "0" } }`,
			`history { item { nested_key: "x" value_json: "1" } }`,
			`exit { exit_code: 0 }`,
		},
	},
	{
		// A new-format log recorded with resume intent set. Pins R2/R5/R9.
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

// TestGoldenLogs_UpToDate is the standard Go golden-file idiom: it
// regenerates every fixture from goldenCorpus and compares bytes against
// what's committed under tests/assets/compat_logs.
//
// A byte mismatch means either goldenCorpus was edited without
// regenerating the corpus, or (rarely) the fixture was hand-edited. Either
// way, run with -update-golden-logs to fix it, then review the diff: that
// diff is the actual reviewable change to what this repo claims an old or
// new .wandb file looks like.
func TestGoldenLogs_UpToDate(t *testing.T) {
	generatedDir := t.TempDir()
	for _, c := range goldenCorpus {
		writeGoldenCase(t, filepath.Join(generatedDir, goldenLogRelPath(c.Name)), c)
	}

	if *updateGoldenLogs {
		for _, c := range goldenCorpus {
			dst := goldenLogPath(c.Name)
			require.NoError(t, os.MkdirAll(filepath.Dir(dst), 0o777))
			copyFile(t,
				filepath.Join(generatedDir, goldenLogRelPath(c.Name)),
				dst)
		}
		t.Skip("regenerated tests/assets/compat_logs;" +
			" re-run without -update-golden-logs to verify")
	}

	for _, c := range goldenCorpus {
		generated, err := os.ReadFile(
			filepath.Join(generatedDir, goldenLogRelPath(c.Name)))
		require.NoError(t, err)

		committed, err := os.ReadFile(goldenLogPath(c.Name))
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

// TestGoldenLogs_SizeBudget keeps tests/assets/compat_logs from becoming a
// dumping ground. There's no clever enforcement here beyond a byte count:
// that's the point.
func TestGoldenLogs_SizeBudget(t *testing.T) {
	const (
		totalBudget       = 64 * 1024
		synthesizedBudget = 4 * 1024
		provenanceBudget  = 16 * 1024
	)

	root := goldenLogDir()

	var synthesized, provenance int64
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		require.NoError(t, err)
		if d.IsDir() {
			return nil
		}
		if !strings.HasSuffix(path, ".wandb") {
			return nil
		}

		info, err := d.Info()
		require.NoError(t, err)

		rel, err := filepath.Rel(root, path)
		require.NoError(t, err)

		if strings.HasPrefix(rel, "provenance"+string(filepath.Separator)) {
			provenance += info.Size()
		} else {
			synthesized += info.Size()
		}
		return nil
	})
	require.NoError(t, err)

	if synthesized > synthesizedBudget {
		t.Errorf("synthesized corpus is %d bytes, budget is %d",
			synthesized, synthesizedBudget)
	}
	if provenance > provenanceBudget {
		t.Errorf("provenance corpus is %d bytes, budget is %d",
			provenance, provenanceBudget)
	}
	if synthesized+provenance > totalBudget {
		t.Errorf("total corpus is %d bytes, budget is %d",
			synthesized+provenance, totalBudget)
	}
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

// copyFile overwrites dst with the contents of src.
func copyFile(t *testing.T, src, dst string) {
	t.Helper()

	contents, err := os.ReadFile(src)
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(dst, contents, 0o666))
}
