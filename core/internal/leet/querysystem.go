package leet

import (
	"cmp"
	"errors"
	"io"
	"maps"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// systemKeyPrefix is what QuerySystem prepends to the name of a system
// metric.
const systemKeyPrefix = "system."

// SystemQuery selects the system metrics of a run for QuerySystem.
type SystemQuery struct {
	Keys  []string `json:"keys"  doc:"System metric keys or globs with * and ? to return, e.g. system.gpu.*.gpu or system.memory*. Defaults to every key."`
	Since string   `json:"since" doc:"Return only the samples taken at or after this RFC 3339 time, or within this duration (e.g. 10m) of the run's last sample, or of now while it runs."`
	Bins  int      `json:"bins"  doc:"Aggregate each metric into this many equal-width bins over time instead of returning rows. Required for a W&B URL, whose system metrics the server serves in bins only, choosing the bin edges itself so about this many come back."`
	Last  int      `json:"last"  doc:"Return only the last N samples."`
	Limit int      `json:"limit" doc:"Samples to return (default 1000)."`
}

func (q SystemQuery) validate() error {
	switch {
	case q.Bins < 0, q.Last < 0, q.Limit < 0:
		return badRequest("bins, last and limit must be >= 0")
	case q.Bins > maxHistoryBins:
		return badRequest("bins must be <= %d", maxHistoryBins)
	case q.Bins > 0 && (q.Last > 0 || q.Limit > 0):
		return badRequest("bins cannot be used with last or limit")
	case q.Last > 0 && q.Limit > 0:
		return badRequest("last cannot be used with limit")
	}
	return nil
}

// QuerySystem writes the system metrics of a run as one JSON object with
// the schema leet.system/1: its samples as rows on _timestamp, or their
// aggregates in equal-width bins with q.Bins, in the shapes of
// QueryHistory. Keys carry the system. prefix, as the W&B UI names them.
//
// The run is runFile when given, else the run in wandbDir that run names,
// else the newest run in wandbDir, as resolveQueryRun decides.
func QuerySystem(wandbDir, runFile, run string, q SystemQuery, w io.Writer) error {
	if err := q.validate(); err != nil {
		return err
	}
	since, sinceAgo, err := parseSince(q.Since)
	if err != nil {
		return err
	}
	path, err := resolveQueryRun(wandbDir, runFile, run)
	if err != nil {
		return err
	}
	if path, err = filepath.Abs(path); err != nil {
		return err
	}
	reader, err := transactionlog.OpenReader(path, observability.NewNoOpLogger())
	if err != nil {
		return err
	}
	defer reader.Close()

	s := &systemScan{q: q, path: path, seen: make(map[string]bool)}
	if err := s.scan(reader); err != nil {
		return err
	}
	stat, err := os.Stat(path)
	if err != nil {
		return err
	}
	state := runState(s.exit, s.run != nil, stat.ModTime())
	if sinceAgo > 0 {
		end := time.Now()
		if state != RunStateRunning && s.last > 0 {
			end = time.Unix(s.last, 0)
		}
		since = end.Add(-sinceAgo)
	}
	if !since.IsZero() {
		s.samples = slices.DeleteFunc(s.samples, func(m StatsMsg) bool {
			return time.Unix(m.Timestamp, 0).Before(since)
		})
	}

	out := s.envelope(state, since)
	if q.Bins > 0 {
		s.bins(out)
	} else {
		s.rows(out)
	}
	return encodeJSON(w, out, "")
}

// systemScan reads the system metrics of one run for QuerySystem.
type systemScan struct {
	q    SystemQuery
	path string
	run  *spb.RunRecord
	exit *spb.RunExitRecord

	// samples holds the selected metrics of every stats record that has
	// one, by prefixed name, in time order; records at the same second
	// merge into one sample.
	samples []StatsMsg
	// last is the unix time of the latest stats record.
	last int64
	// seen is every prefixed name in the file.
	seen map[string]bool
	// scanned counts the stats records decoded.
	scanned  int
	warnings []string
}

// scan reads records up to the end of the file, keeping the selected
// metrics of every stats record.
func (s *systemScan) scan(reader *transactionlog.Reader) error {
	bySecond := make(map[int64]map[string]float64)
	for {
		record, err := readRecord(reader)
		switch {
		case errors.Is(err, io.EOF), errors.Is(err, io.ErrUnexpectedEOF):
			for _, ts := range slices.Sorted(maps.Keys(bySecond)) {
				s.samples = append(s.samples, StatsMsg{Timestamp: ts, Metrics: bySecond[ts]})
			}
			return nil
		case errors.Is(err, errCorruptSkipped):
			s.warnings = append(s.warnings, err.Error())
			continue
		case err != nil:
			return err
		}
		switch rec := record.RecordType.(type) {
		case *spb.Record_Run:
			if s.run == nil {
				s.run = rec.Run
			}
		case *spb.Record_Exit:
			s.exit = rec.Exit
		case *spb.Record_Stats:
			msg, ok := ParseStats(s.path, rec.Stats).(StatsMsg)
			if !ok || rec.Stats.Timestamp == nil {
				continue
			}
			s.scanned++
			s.last = max(s.last, msg.Timestamp)
			selected := make(map[string]float64, len(msg.Metrics))
			for key, v := range msg.Metrics {
				key = systemKeyPrefix + key
				s.seen[key] = true
				if len(s.q.Keys) == 0 ||
					slices.ContainsFunc(s.q.Keys, func(p string) bool { return matchKey(p, key) }) {
					selected[key] = v
				}
			}
			if len(selected) == 0 {
				continue
			}
			if prev := bySecond[msg.Timestamp]; prev != nil {
				maps.Copy(prev, selected)
			} else {
				bySecond[msg.Timestamp] = selected
			}
		}
	}
}

// envelope returns the fields shared by the rows and bins objects.
func (s *systemScan) envelope(state RunState, since time.Time) map[string]any {
	requested := s.q.Keys
	if requested == nil {
		requested = []string{}
	}
	warnings := append([]string{}, s.warnings...)
	warnings = append(warnings, unmatchedKeyWarnings(s.q.Keys, sortedKeys(s.seen))...)
	out := map[string]any{
		"schema": "leet.system/1",
		"source": querySource(
			s.path, s.run.GetEntity(), s.run.GetProject(), s.run.GetRunId(),
		),
		"state":            strings.ToLower(state.String()),
		"exit_code":        nil,
		"run_id":           orNil(s.run.GetRunId()),
		"run_name":         orNil(s.run.GetDisplayName()),
		"requested_keys":   requested,
		"keys":             []string{},
		"x_axis":           "_timestamp",
		"skipped_keys":     map[string]any{},
		"exact":            len(s.warnings) == 0,
		"retrieval_method": "local_scan",
		"rows_scanned":     s.scanned,
		"coverage": map[string]any{
			"first_x":         nil,
			"last_x":          nil,
			"requested_since": rfc3339OrNil(since),
		},
		"truncated":   false,
		"has_more":    false,
		"next_cursor": nil,
		"warnings":    warnings,
	}
	if s.exit != nil {
		out["exit_code"] = s.exit.GetExitCode()
	}
	return out
}

// rows adds the samples as rows to out: the last q.Last of them, else the
// first q.Limit.
func (s *systemScan) rows(out map[string]any) {
	samples := s.samples
	if last := s.q.Last; last > 0 {
		samples = samples[max(len(samples)-last, 0):]
	} else if limit := cmp.Or(s.q.Limit, defaultHistoryLimit); len(samples) > limit {
		samples = samples[:limit]
	}
	keys := make(map[string]bool)
	rows := make([]any, 0, len(samples))
	for _, m := range samples {
		row := make(map[string]any, len(m.Metrics)+1)
		row["_timestamp"] = float64(m.Timestamp)
		for key, v := range m.Metrics {
			row[key] = v
			keys[key] = true
		}
		rows = append(rows, row)
	}
	out["rows"] = rows
	out["keys"] = sortedKeys(keys)
	out["truncated"] = len(samples) < len(s.samples)
	if len(samples) > 0 {
		coverage := out["coverage"].(map[string]any)
		coverage["first_x"] = float64(samples[0].Timestamp)
		coverage["last_x"] = float64(samples[len(samples)-1].Timestamp)
	}
}

// sortedKeys returns the keys of m in order, as a list even when empty.
func sortedKeys[V any](m map[string]V) []string {
	keys := slices.AppendSeq(make([]string, 0, len(m)), maps.Keys(m))
	slices.Sort(keys)
	return keys
}

// bins adds the samples as series of q.Bins bins to out, every series over
// the same time range, each with the title of its metric and the unit of
// its values as UnitFormatter prints 1 of them, when LEET knows it.
func (s *systemScan) bins(out map[string]any) {
	series := make(map[string]*binSeries)
	lo, hi := math.Inf(1), math.Inf(-1)
	for _, m := range s.samples {
		x := float64(m.Timestamp)
		lo, hi = min(lo, x), max(hi, x)
		for key, y := range m.Metrics {
			ser := series[key]
			if ser == nil {
				ser = &binSeries{}
				series[key] = ser
			}
			ser.xs = append(ser.xs, x)
			ser.ys = append(ser.ys, y)
		}
	}

	keys := sortedKeys(series)
	list := make([]any, 0, len(keys))
	for _, key := range keys {
		entry := map[string]any{
			"key":    key,
			"x_axis": "_timestamp",
			"count":  len(series[key].xs),
			"bins":   bin(series[key].xs, series[key].ys, lo, hi, s.q.Bins),
		}
		entry["title"], entry["unit"] = systemMetricTitleUnit(key)
		list = append(list, entry)
	}
	out["series"] = list
	out["keys"] = keys
	if len(keys) > 0 {
		coverage := out["coverage"].(map[string]any)
		coverage["first_x"], coverage["last_x"] = lo, hi
	}
}

// systemMetricTitleUnit returns the title of a system metric and the unit
// of its values as UnitFormatter prints 1 of them, when LEET knows the
// metric, else nils.
func systemMetricTitleUnit(key string) (title, unit any) {
	def := MatchMetricDef(strings.TrimPrefix(key, systemKeyPrefix))
	if def == nil {
		return nil, nil
	}
	return def.Name, orNil(strings.TrimPrefix(def.Unit.Format(1), "1"))
}
