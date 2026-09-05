package runreader

import (
	"context"
	"errors"
	"io"
	"maps"
	"os"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/internal/runenvironment"
	"github.com/wandb/wandb/core/internal/runsummary"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// State is a run's state as far as its transaction log tells.
type State string

const (
	// StatePending means no run record has been read yet.
	StatePending State = "pending"
	StateRunning State = "running"
	// StateFinished means the run exited with code 0.
	StateFinished State = "finished"
	// StateFailed means the run exited with a nonzero code.
	StateFailed State = "failed"
	// StateCrashed means the run reported a crash, or has no exit record
	// and its file has not changed for crashTimeout.
	StateCrashed State = "crashed"
)

// crashTimeout is how long a run's file may go unchanged before a run
// without an exit record is presumed crashed.
const crashTimeout = 10 * time.Minute

// crashExitCode is the exit code the SDK reports for a run that crashed.
const crashExitCode = 254

// Info is the identity of a run from its run record.
type Info struct {
	RunID       string
	Entity      string
	Project     string
	DisplayName string
	Notes       string
	Tags        []string
	Group       string
	JobType     string
	SweepID     string
	Host        string
	StartTime   time.Time
}

func infoFromRecord(rec *spb.RunRecord) Info {
	info := Info{
		RunID:       rec.GetRunId(),
		Entity:      rec.GetEntity(),
		Project:     rec.GetProject(),
		DisplayName: rec.GetDisplayName(),
		Notes:       rec.GetNotes(),
		Tags:        slices.Clone(rec.GetTags()),
		Group:       rec.GetRunGroup(),
		JobType:     rec.GetJobType(),
		SweepID:     rec.GetSweepId(),
		Host:        rec.GetHost(),
	}
	if ts := rec.GetStartTime(); ts != nil {
		info.StartTime = ts.AsTime()
	}
	return info
}

// Run is a run's state folded from its transaction log.
//
// Update reads the records written since the last call, so a Run kept open
// follows a live run cheaply. History rows are not retained; see
// ScanHistory.
type Run struct {
	path   string
	cursor *Cursor

	info        Info
	infoSeen    bool
	config      *runconfig.RunConfig
	summary     *runsummary.RunSummary
	environment *runenvironment.RunEnvironment
	console     *Console
	exit        *spb.RunExitRecord
	lastStep    int64
	historyKeys map[string]struct{}
}

// Open prepares to read the transaction log at path. Nothing is read until
// Update is called.
func Open(path string, logger *observability.CoreLogger) (*Run, error) {
	cursor, err := OpenCursor(path, logger)
	if err != nil {
		return nil, err
	}
	return &Run{
		path:        path,
		cursor:      cursor,
		config:      runconfig.New(),
		summary:     runsummary.New(),
		console:     NewConsole(),
		lastStep:    -1,
		historyKeys: make(map[string]struct{}),
	}, nil
}

// Update folds every record written since the last call.
//
// It returns nil once all available data has been read, ctx's error if ctx
// is done first, or the read error if the file cannot be read.
func (r *Run) Update(ctx context.Context) error {
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		record, err := r.cursor.Next()
		if errors.Is(err, io.EOF) {
			return nil
		}
		if err != nil {
			return err
		}
		r.apply(record)
	}
}

func (r *Run) apply(record *spb.Record) {
	switch rec := record.RecordType.(type) {
	case *spb.Record_Run:
		r.info = infoFromRecord(rec.Run)
		r.infoSeen = true
		if cfg := rec.Run.GetConfig(); cfg != nil {
			r.config.ApplyChangeRecord(cfg, func(error) {})
		}
	case *spb.Record_Config:
		r.config.ApplyChangeRecord(rec.Config, func(error) {})
	case *spb.Record_Summary:
		_ = runsummary.FromProto(rec.Summary).Apply(r.summary)
	case *spb.Record_Environment:
		if r.environment == nil {
			r.environment = runenvironment.New(rec.Environment.GetWriterId())
		}
		r.environment.ProcessRecord(rec.Environment)
	case *spb.Record_History:
		r.lastStep = max(r.lastStep, historyStep(rec.History))
		for _, item := range rec.History.GetItem() {
			if key := historyItemKey(item); key != "" {
				r.historyKeys[key] = struct{}{}
			}
		}
	case *spb.Record_OutputRaw:
		r.console.Process(rec.OutputRaw)
	case *spb.Record_Exit:
		r.exit = rec.Exit
	}
}

// Info returns the run's identity. Zero until a run record is read.
func (r *Run) Info() Info { return r.info }

// State derives the run's state from the exit record, or from the file's
// age when there is none.
func (r *Run) State() State {
	var modTime time.Time
	if stat, err := os.Stat(r.path); err == nil {
		modTime = stat.ModTime()
	}
	return deriveState(r.exit, r.infoSeen, modTime, time.Now())
}

func deriveState(
	exit *spb.RunExitRecord,
	infoSeen bool,
	modTime, now time.Time,
) State {
	switch {
	case exit != nil && exit.GetExitCode() == 0:
		return StateFinished
	case exit != nil && exit.GetExitCode() == crashExitCode:
		return StateCrashed
	case exit != nil:
		return StateFailed
	case !modTime.IsZero() && now.Sub(modTime) > crashTimeout:
		return StateCrashed
	case infoSeen:
		return StateRunning
	default:
		return StatePending
	}
}

// ExitCode returns the run's exit code and whether the run has exited.
func (r *Run) ExitCode() (int32, bool) {
	if r.exit == nil {
		return 0, false
	}
	return r.exit.GetExitCode(), true
}

// LastStep is the highest history step read, or -1 if there is no history.
func (r *Run) LastStep() int64 { return r.lastStep }

// HistoryKeys returns the sorted keys logged to the run's history.
func (r *Run) HistoryKeys() []string {
	return slices.Sorted(maps.Keys(r.historyKeys))
}

// ConfigJSON is the run's config as a JSON object.
func (r *Run) ConfigJSON() ([]byte, error) {
	return simplejsonext.Marshal(r.config.CloneTree())
}

// SummaryJSON is the run's summary as a JSON object.
func (r *Run) SummaryJSON() ([]byte, error) {
	return r.summary.Serialize()
}

// EnvironmentJSON is the run's environment (the contents of
// wandb-metadata.json) as a JSON object, or nil if none was recorded.
func (r *Run) EnvironmentJSON() ([]byte, error) {
	if r.environment == nil {
		return nil, nil
	}
	return r.environment.ToJSON()
}

// Console returns the run's console output assembled so far.
func (r *Run) Console() []ConsoleLine { return r.console.Lines() }

func (r *Run) Close() { r.cursor.Close() }

// historyStep returns a history record's step, falling back to its _step
// item for records without an explicit step.
func historyStep(h *spb.HistoryRecord) int64 {
	if step := h.GetStep(); step != nil {
		return step.GetNum()
	}
	for _, item := range h.GetItem() {
		if historyItemKey(item) != "_step" {
			continue
		}
		if v, err := strconv.ParseInt(strings.TrimSpace(item.GetValueJson()), 10, 64); err == nil {
			return v
		}
	}
	return 0
}

// historyItemKey is the dotted nested key, or the flat key when there is none.
func historyItemKey(item *spb.HistoryItem) string {
	if key := strings.Join(item.GetNestedKey(), "."); key != "" {
		return key
	}
	return item.GetKey()
}
