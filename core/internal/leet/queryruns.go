package leet

import (
	"cmp"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"golang.org/x/sync/errgroup"

	"github.com/wandb/wandb/core/internal/observability"
)

// defaultRunsLimit is how many runs ListRuns returns unless told otherwise.
const defaultRunsLimit = 200

// RunsQuery selects the runs ListRuns returns.
type RunsQuery struct {
	Filter      string   `json:"filter"       doc:"List only the runs matching this filter, in the language of the LEET runs sidebar, e.g. 'name:resnet cfg.lr>=0.001'."`
	Glob        bool     `json:"glob"         doc:"Match the patterns of the filter as globs instead of regexes."`
	SummaryKeys []string `json:"summary_keys" doc:"Summary keys or globs with * and ? to return per run, e.g. val/loss or train/*, as updated in the last 2 MiB of the file. A glob never matches keys starting with _. Local paths only; for a W&B URL read the run's summary instead."`
	Limit       int      `json:"limit"        doc:"Runs to return, 0 for the default of 200."`
}

// ListRuns writes the runs of a wandb directory, newest first, as one JSON
// object with the schema leet.runs/1. Each run's identity comes from the
// first records of its .wandb file and its state, exit code, last step and,
// with q.SummaryKeys, latest summary values from the last records. The one
// run that QueryRunFile names from runFile and wandbDir is listed alone.
func ListRuns(wandbDir, runFile string, q RunsQuery, w io.Writer) error {
	if q.Limit < 0 {
		return badRequest("limit must be >= 0")
	}
	limit := cmp.Or(q.Limit, defaultRunsLimit)

	file := QueryRunFile(wandbDir, runFile)
	path, err := filepath.Abs(cmp.Or(file, wandbDir))
	if err != nil {
		return err
	}
	var listings []runListing
	if file != "" {
		if _, err := os.Stat(path); err != nil {
			return err
		}
		wandbDir = filepath.Dir(filepath.Dir(path))
		listings = []runListing{{key: filepath.Base(filepath.Dir(path)), file: path}}
	} else {
		wandbDir = path
		runKeys, err := scanWandbRunDirs(wandbDir)
		if err != nil {
			return err
		}
		for _, key := range runKeys {
			if file := runWandbFile(wandbDir, key); file != "" {
				listings = append(listings, runListing{key: key, file: file})
			}
		}
	}

	total := len(listings)
	if q.Filter == "" {
		listings = listings[:min(limit, len(listings))]
	}
	var g errgroup.Group
	g.SetLimit(maxConcurrentPreloads)
	for i := range listings {
		g.Go(func() error { listings[i].read(); return nil })
	}
	_ = g.Wait()

	if q.Filter != "" {
		mode := FilterModeRegex
		if q.Glob {
			mode = FilterModeGlob
		}
		query := CompileRunFilterQuery(q.Filter, mode)
		listings = slices.DeleteFunc(listings, func(l runListing) bool {
			return !query.Match(buildWorkspaceRunFilterData(l.key, l.run))
		})
		total = len(listings)
		listings = listings[:min(limit, len(listings))]
	}

	ds := loadDirState(wandbDir, observability.NewNoOpLogger())
	runs := make([]any, 0, len(listings))
	for i := range listings {
		runs = append(runs, listings[i].json(q.SummaryKeys, ds))
	}
	return encodeJSON(w, map[string]any{
		"schema":    "leet.runs/1",
		"source":    map[string]any{"kind": "local", "path": path, "url": nil},
		"runs":      runs,
		"total":     total,
		"truncated": total > len(runs),
		"warnings":  []string{},
	}, "")
}

// runListing is what the first and last records of a run's .wandb file say
// about it.
type runListing struct {
	key, file string
	run       RunMsg
	tail      runTail
	lastWrite time.Time
}

func (l *runListing) read() {
	if run := readRunRecord(l.file); run != nil {
		l.run = runMsgFromRecord(l.file, run)
	}
	var size int64
	if stat, err := os.Stat(l.file); err == nil {
		l.lastWrite, size = stat.ModTime(), stat.Size()
	}
	l.tail = readRunTail(l.file, size)
}

func (l *runListing) json(summaryKeys []string, ds *dirState) map[string]any {
	state, detail := runStateDetail(l.tail.exit, l.run.ID != "", l.lastWrite)
	out := map[string]any{
		"run_key":      l.key,
		"run_id":       orNil(l.run.ID),
		"name":         orNil(l.run.DisplayName),
		"entity":       orNil(l.run.Entity),
		"project":      orNil(l.run.Project),
		"state":        strings.ToLower(state.String()),
		"state_detail": detail,
		"start_time":   rfc3339OrNil(l.run.StartTime),
		"last_write":   rfc3339OrNil(l.lastWrite),
		"exit_code":    nil,
		"step":         nil,
		"tags":         append([]string{}, l.run.Tags...),
		"notes":        orNil(l.run.Notes),
		"file":         nil,
		"selected":     slices.Contains(ds.SelectedRuns, l.key),
		"pinned":       ds.PinnedRun == l.key,
	}
	if !l.lastWrite.IsZero() {
		out["file"] = l.file
	}
	if l.tail.exit != nil {
		out["exit_code"] = l.tail.exit.GetExitCode()
	}
	if l.tail.step >= 0 {
		out["step"] = l.tail.step
	}
	if len(summaryKeys) > 0 {
		out["summary"] = nil
		if l.tail.summary != nil {
			values := make(map[string]any)
			for key, value := range l.tail.summary {
				if slices.ContainsFunc(summaryKeys, func(p string) bool {
					return matchKey(p, key)
				}) {
					values[key] = value
				}
			}
			out["summary"] = values
		}
	}
	return out
}

func rfc3339OrNil(t time.Time) any {
	if t.IsZero() {
		return nil
	}
	return t.UTC().Format(time.RFC3339)
}
