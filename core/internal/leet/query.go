package leet

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// QueryError is an error that a query verb reports to its caller with a
// code: run_not_found, path_not_found or bad_request.
type QueryError struct {
	Code    string
	Message string
}

func (e *QueryError) Error() string { return e.Message }

func badRequest(format string, args ...any) error {
	return &QueryError{Code: "bad_request", Message: fmt.Sprintf(format, args...)}
}

// WriteQueryError writes err as one line of JSON:
//
//	{"schema":"leet.error/1","error":"bad_request","message":"..."}
//
// An error that is not a QueryError has the code "path_not_found" when a
// file or directory does not exist and "internal" otherwise.
func WriteQueryError(w io.Writer, err error) {
	code := "internal"
	var qerr *QueryError
	switch {
	case errors.As(err, &qerr):
		code = qerr.Code
	case errors.Is(err, fs.ErrNotExist):
		code = "path_not_found"
	}
	_ = encodeJSON(w, map[string]any{
		"schema":  "leet.error/1",
		"error":   code,
		"message": err.Error(),
	}, "")
}

// historyCursor is where a page of history rows ended, for the call that
// continues after it, with the define_metric rules and the highest step
// seen before that point.
type historyCursor struct {
	Version int         `json:"v"`
	Offset  int64       `json:"o"`
	RunID   string      `json:"f"`
	Size    int64       `json:"n"`
	Metrics []metricDef `json:"m"`
	MaxStep int64       `json:"t"`
}

// metricDef is a define_metric rule: the step metric of a key or of a glob.
type metricDef struct {
	Name string `json:"n,omitempty"`
	Glob string `json:"g,omitempty"`
	Step string `json:"s"`
}

func encodeCursor(c any) string {
	b, _ := json.Marshal(c)
	return base64.RawURLEncoding.EncodeToString(b)
}

// decodeCursor decodes a cursor into c, a pointer to a cursor struct.
func decodeCursor(s string, c any) error {
	b, err := base64.RawURLEncoding.DecodeString(s)
	if err == nil {
		err = json.Unmarshal(b, c)
	}
	if err != nil {
		return badRequest("after: not a cursor from a previous call")
	}
	return nil
}

// queryRunFile returns the one .wandb file a query names: runFile when
// given, else wandbDir itself when it is a file, else the .wandb file of
// the run directory wandbDir names, else "".
func queryRunFile(wandbDir, runFile string) string {
	if runFile != "" {
		return runFile
	}
	if info, err := os.Stat(wandbDir); err == nil && !info.IsDir() {
		return wandbDir
	}
	if id := extractRunID(filepath.Base(wandbDir)); id != "" {
		return filepath.Join(wandbDir, "run-"+id+".wandb")
	}
	return ""
}

// resolveQueryRun returns the .wandb file a query reads: the one
// queryRunFile names, else the run in wandbDir that run names by its
// directory, its ID or its display name, else the newest run in wandbDir.
func resolveQueryRun(wandbDir, runFile, run string) (string, error) {
	if runFile := queryRunFile(wandbDir, runFile); runFile != "" {
		if run != "" {
			return "", badRequest("run cannot be used with a run's path")
		}
		return runFile, nil
	}

	runKeys, err := scanWandbRunDirs(wandbDir)
	if err != nil {
		return "", err
	}
	runKeys = slices.DeleteFunc(runKeys, func(key string) bool {
		return runWandbFile(wandbDir, key) == ""
	})

	if run == "" {
		if len(runKeys) > 0 {
			return runWandbFile(wandbDir, runKeys[0]), nil
		}
		path, err := resolveWandbFile("", wandbDir)
		if err != nil {
			return "", &QueryError{
				Code:    "run_not_found",
				Message: fmt.Sprintf("no runs in %q", wandbDir),
			}
		}
		return path, nil
	}

	for _, key := range runKeys {
		if key == run || extractRunID(key) == run {
			return runWandbFile(wandbDir, key), nil
		}
	}
	var named []string
	for _, key := range runKeys {
		if readRunRecord(runWandbFile(wandbDir, key)).GetDisplayName() == run {
			named = append(named, key)
		}
	}
	switch len(named) {
	case 0:
		return "", &QueryError{
			Code:    "run_not_found",
			Message: fmt.Sprintf("no run %q in %q", run, wandbDir),
		}
	case 1:
		return runWandbFile(wandbDir, named[0]), nil
	}
	ids := make([]string, len(named))
	for i, key := range named {
		ids[i] = extractRunID(key)
	}
	return "", badRequest("%d runs are named %q: name one by ID: %s",
		len(named), run, strings.Join(ids, ", "))
}

// readRunRecord returns the run record among the first maxRecordsToScan
// records of a .wandb file, or nil.
func readRunRecord(path string) *spb.RunRecord {
	reader, err := transactionlog.OpenReader(path, observability.NewNoOpLogger())
	if err != nil {
		return nil
	}
	defer reader.Close()

	for range maxRecordsToScan {
		record, err := reader.Read()
		if err != nil {
			return nil
		}
		if run := record.GetRun(); run != nil {
			return run
		}
	}
	return nil
}

// queryTailBytes is how far from the end of a .wandb file readRunTail
// starts reading: 64 LevelDB blocks.
const queryTailBytes = 64 * 32 * 1024

// runTail is what the last records of a .wandb file say about a run.
type runTail struct {
	exit *spb.RunExitRecord
	// step is the higher of the highest history step and the summary's
	// _step, or -1.
	step int64
	// summary holds the summary values updated within the tail by top-level
	// key, nested values assembled as wandb leet inspect --summary shows
	// them, or is nil when no summary record was read.
	summary map[string]any
}

// readRunTail reads the records in the last queryTailBytes of a .wandb file
// of the given size, or all of a shorter file, leaving out a record that
// started before the tail.
func readRunTail(path string, size int64) runTail {
	tail := runTail{step: -1}
	reader, err := transactionlog.OpenReader(path, observability.NewNoOpLogger())
	if err != nil {
		return tail
	}
	defer reader.Close()

	if start := (size - queryTailBytes) &^ (32*1024 - 1); start > 0 {
		if err := reader.SeekRecord(start); err != nil {
			return tail
		}
	}
	var summary *runsummary.RunSummary
	for {
		record, err := readRecord(reader)
		if errors.Is(err, errCorruptSkipped) {
			continue
		}
		if err != nil {
			break
		}
		switch rec := record.RecordType.(type) {
		case *spb.Record_Exit:
			tail.exit = rec.Exit
		case *spb.Record_History:
			if step, ok := historyStep(rec.History); ok {
				tail.step = max(tail.step, step)
			}
		case *spb.Record_Summary:
			if summary == nil {
				summary = runsummary.New()
			}
			_ = runsummary.FromProto(rec.Summary).Apply(summary)
		}
	}
	if summary != nil {
		tail.summary = summary.ToNestedMaps()
		if step, ok := tail.summary["_step"].(int64); ok {
			tail.step = max(tail.step, step)
		}
	}
	return tail
}

// querySource returns the source field of a query object for a local run.
func querySource(path, entity, project, runID string) map[string]any {
	return map[string]any{
		"kind":    "local",
		"path":    path,
		"url":     nil,
		"entity":  orNil(entity),
		"project": orNil(project),
		"run_id":  orNil(runID),
	}
}

// matchKey reports whether key matches pattern: the key itself, or a glob
// with * and ? anchored at both ends. A glob never matches an internal key
// starting with "_".
func matchKey(pattern, key string) bool {
	if !strings.ContainsAny(pattern, "*?") {
		return pattern == key
	}
	return !strings.HasPrefix(key, "_") && wildcardMatch(pattern, key)
}
