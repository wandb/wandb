package leet

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"maps"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runmetric"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// defaultHistoryLimit is how many rows QueryHistory returns per call
	// unless told otherwise.
	defaultHistoryLimit = 1000

	// maxHistoryBins bounds HistoryQuery.Bins.
	maxHistoryBins = 100_000
)

// HistoryQuery selects the metric series of a run for QueryHistory.
type HistoryQuery struct {
	Keys        []string      `json:"keys"         doc:"Metric keys or globs with * and ? to return, e.g. train/loss or val/*. A glob never matches keys starting with _."`
	XAxis       string        `json:"x_axis"       doc:"Key to use as the x axis of every metric instead of its own, e.g. _runtime. Rows without a finite value for it are left out."`
	Bins        int           `json:"bins"         doc:"Aggregate each metric into this many equal-width bins over its x range instead of returning rows. For a W&B URL the server chooses the bin edges, so about this many bins come back, each with x0 and x1 the first and last x it observed."`
	MinStep     *int64        `json:"min_step"     doc:"First _step to include."`
	MaxStep     *int64        `json:"max_step"     doc:"Last _step to include."`
	Last        int           `json:"last"         doc:"Return only the last N rows, or for a W&B URL the rows of the last N steps."`
	Limit       int           `json:"limit"        doc:"Rows per call (default 1000)."`
	After       string        `json:"after"        doc:"The next_cursor of a previous call, to continue after the rows it returned."`
	Follow      bool          `json:"follow"       doc:"Keep printing new rows as the run writes them, one JSON object per poll, until it exits. Local runs only."`
	IdleTimeout time.Duration `json:"idle_timeout" doc:"With --follow, stop once the run's file has gone this long without a write. 0 waits forever."`
}

func (q HistoryQuery) validate() error {
	switch {
	case len(q.Keys) == 0:
		return badRequest("keys required")
	case q.Bins < 0, q.Last < 0, q.Limit < 0, q.IdleTimeout < 0:
		return badRequest("bins, last, limit and idle_timeout must be >= 0")
	case q.MinStep != nil && q.MaxStep != nil && *q.MinStep > *q.MaxStep:
		return badRequest("min_step must be <= max_step")
	case q.Bins > maxHistoryBins:
		return badRequest("bins must be <= %d", maxHistoryBins)
	case q.Bins > 0 && (q.Last > 0 || q.Limit > 0 || q.After != "" || q.Follow):
		return badRequest("bins cannot be used with last, limit, after or follow")
	case q.Last > 0 && q.Limit > 0:
		return badRequest("last cannot be used with limit")
	}
	return nil
}

// QueryHistory writes the metric series of a run as one JSON object with the
// schema leet.history/1: its history rows, or their aggregates in equal-width
// bins with q.Bins. With q.Follow it keeps writing one object per poll with
// the new rows until the run exits or its file goes q.IdleTimeout without a
// write.
//
// The run is runFile when given, else the run in wandbDir that run names,
// else the newest run in wandbDir, as resolveQueryRun decides.
func QueryHistory(wandbDir, runFile, run string, q HistoryQuery, w io.Writer) error {
	if err := q.validate(); err != nil {
		return err
	}
	path, err := resolveQueryRun(wandbDir, runFile, run)
	if err != nil {
		return err
	}
	if path, err = filepath.Abs(path); err != nil {
		return err
	}
	stat, err := os.Stat(path)
	if err != nil {
		return err
	}
	reader, err := transactionlog.OpenReader(path, observability.NewNoOpLogger())
	if err != nil {
		return err
	}
	defer reader.Close()

	s := &historyScan{
		q:          q,
		path:       path,
		reader:     reader,
		metrics:    runmetric.New(),
		run:        readRunRecord(path),
		exit:       readRunTail(path, stat.Size()).exit,
		values:     make(map[string]float64),
		axes:       make(map[string]string),
		nonNumeric: make(map[string]bool),
		maxStep:    -1,
	}
	if q.After != "" {
		var c historyCursor
		if err := decodeCursor(q.After, &c); err != nil {
			return err
		}
		switch {
		case c.Version != 1:
			return badRequest("after: unsupported cursor version")
		case c.RunID != s.run.GetRunId(), c.Size > stat.Size(), c.Offset > stat.Size():
			return badRequest("after: the cursor is from another run or an older file")
		}
		for _, d := range c.Metrics {
			_ = s.metrics.ProcessRecord(&spb.MetricRecord{
				Name: d.Name, GlobName: d.Glob, StepMetric: d.Step,
			})
		}
		s.defs = c.Metrics
		s.maxStep = c.MaxStep
		if err := reader.SeekRecord(c.Offset); err != nil {
			return err
		}
	}

	if q.Bins > 0 {
		return s.writeBins(w)
	}
	return s.writeRows(w)
}

// historyScan reads the history of one run for QueryHistory.
type historyScan struct {
	q       HistoryQuery
	path    string
	reader  *transactionlog.Reader
	metrics *runmetric.MetricHandler
	// defs holds the define_metric rules seen so far, for the cursor.
	defs []metricDef

	run  *spb.RunRecord
	exit *spb.RunExitRecord

	// values holds one record's numeric items and is reused across records.
	values map[string]float64
	// axes is the x axis of every selected key seen with a numeric value.
	axes map[string]string
	// nonNumeric holds the selected keys seen without a numeric value.
	nonNumeric map[string]bool
	// xSeen is whether any record held a value for q.XAxis.
	xSeen bool
	// corrupt is whether the scan skipped corrupt data since the last object
	// was written, so that its rows may be missing.
	corrupt  bool
	warnings []string

	// offset is where the next read starts, which a cursor records.
	offset int64
	// atEOF is whether the last scan reached the end of the file or the
	// exit record, so that nothing more can be read until the file grows.
	atEOF       bool
	rowsScanned int
	// maxStep is the highest step seen, or -1.
	maxStep int64
}

// scan reads records up to the exit record or the end of the file, passing
// each history record to visit until it returns false, which leaves that
// record for the next scan.
func (s *historyScan) scan(visit func(*spb.HistoryRecord) bool) error {
	for {
		before := s.reader.NextRecordOffset()
		record, err := readRecord(s.reader)
		switch {
		case errors.Is(err, io.EOF), errors.Is(err, io.ErrUnexpectedEOF):
			s.offset, s.atEOF = before, true
			return nil
		case errors.Is(err, errCorruptSkipped):
			s.corrupt = true
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
		case *spb.Record_Metric:
			_ = s.metrics.ProcessRecord(rec.Metric)
			if m := rec.Metric; m.GetStepMetric() != "" {
				s.defs = append(s.defs, metricDef{
					Name: m.GetName(), Glob: m.GetGlobName(), Step: m.GetStepMetric(),
				})
			}
		case *spb.Record_Exit:
			s.exit, s.atEOF = rec.Exit, true
			return nil
		case *spb.Record_History:
			if !visit(rec.History) {
				s.offset, s.atEOF = before, false
				return nil
			}
			s.rowsScanned++
		}
	}
}

// rowValues fills s.values with a history record's numeric items and returns
// its step, or false when the record has no step or is outside the requested
// step range.
func (s *historyScan) rowValues(h *spb.HistoryRecord) (int64, bool) {
	step, ok := historyRowValues(h, s.values)
	if !ok {
		return 0, false
	}
	s.values["_step"] = float64(step)
	if _, ok := s.values[s.q.XAxis]; ok {
		s.xSeen = true
	}
	s.maxStep = max(s.maxStep, step)
	if (s.q.MinStep != nil && step < *s.q.MinStep) || (s.q.MaxStep != nil && step > *s.q.MaxStep) {
		return 0, false
	}
	for _, item := range h.GetItem() {
		if _, _, ok := historyMediaField(item); ok {
			continue
		}
		key := historyItemKey(item)
		if _, ok := s.values[key]; ok || key == "" || !s.selected(key) {
			continue
		}
		s.nonNumeric[key] = true
	}
	return step, true
}

// selected reports whether key matches any of the requested keys.
func (s *historyScan) selected(key string) bool {
	return slices.ContainsFunc(s.q.Keys, func(p string) bool { return matchKey(p, key) })
}

// axis returns the x axis of a selected key.
func (s *historyScan) axis(key string) string {
	if s.q.XAxis != "" {
		return s.q.XAxis
	}
	return cmp.Or(s.metrics.StepMetric(key), "_step")
}

// row returns the selected values of a history record with its _step,
// _runtime, _timestamp and the x axis of each selected key, or nil when the
// record has no selected value or no finite value for q.XAxis.
func (s *historyScan) row(h *spb.HistoryRecord) map[string]any {
	step, ok := s.rowValues(h)
	if !ok {
		return nil
	}
	if s.q.XAxis != "" {
		if x, ok := s.values[s.q.XAxis]; !ok || !isFinite(x) {
			return nil
		}
	}

	var row map[string]any
	for key, v := range s.values {
		if !s.selected(key) {
			continue
		}
		if row == nil {
			row = make(map[string]any)
		}
		row[key] = v
		axis := s.axis(key)
		s.axes[key] = axis
		if x, ok := s.values[axis]; ok && axis != "_step" {
			row[axis] = x
		}
	}
	if row == nil {
		return nil
	}
	row["_step"] = step
	for _, key := range []string{"_runtime", "_timestamp"} {
		if v, ok := s.values[key]; ok {
			row[key] = v
		}
	}
	return row
}

// readPage reads rows until the end of the file, or with limit > 0 until
// the row after the first limit rows, which it leaves for the next page.
// With last > 0 it keeps only the last rows and reports how many it left
// out that way.
func (s *historyScan) readPage(limit, last int) (rows []any, dropped int, err error) {
	err = s.scan(func(h *spb.HistoryRecord) bool {
		if limit > 0 && len(rows) == limit {
			// Only peek: the next page returns this row and records its keys.
			axes, nonNumeric := maps.Clone(s.axes), maps.Clone(s.nonNumeric)
			defer func() { s.axes, s.nonNumeric = axes, nonNumeric }()
			return s.row(h) == nil
		}
		row := s.row(h)
		if row == nil {
			return true
		}
		rows = append(rows, row)
		if last > 0 && len(rows) > last {
			rows, dropped = rows[1:], dropped+1
		}
		return true
	})
	return rows, dropped, err
}

func (s *historyScan) writeRows(w io.Writer) error {
	limit := cmp.Or(s.q.Limit, defaultHistoryLimit)
	var rows []any
	var dropped int
	var err error
	if s.q.Last > 0 {
		rows, dropped, err = s.readPage(0, s.q.Last)
	} else {
		rows, dropped, err = s.readPage(limit, 0)
	}
	if err != nil {
		return err
	}
	if err := s.writeObject(w, rows, dropped > 0 || !s.atEOF, !s.atEOF, nil); err != nil {
		return err
	}

	for s.q.Follow && !s.done() {
		if s.atEOF {
			idle, err := awaitWrite(s.reader, s.path, s.q.IdleTimeout)
			if err != nil {
				return err
			}
			if idle > 0 {
				return s.writeObject(w, nil, false, true,
					[]string{fmt.Sprintf("no writes for %v", idle.Round(time.Second))})
			}
		}
		rows, _, err = s.readPage(limit, 0)
		if err != nil {
			return err
		}
		if len(rows) > 0 || !s.atEOF || s.done() {
			if err := s.writeObject(w, rows, !s.atEOF, !s.atEOF, nil); err != nil {
				return err
			}
		}
	}
	return nil
}

// done is whether the run has exited and everything up to its exit record
// was read.
func (s *historyScan) done() bool {
	return s.exit != nil && s.atEOF
}

func (s *historyScan) writeObject(
	w io.Writer,
	rows []any,
	truncated, hasMore bool,
	warnings []string,
) error {
	out, err := s.envelope(warnings)
	if err != nil {
		return err
	}
	if rows == nil {
		rows = []any{}
	}
	out["rows"] = rows
	out["truncated"] = truncated
	out["has_more"] = hasMore
	if len(rows) > 0 {
		x := cmp.Or(s.q.XAxis, "_step")
		out["coverage"].(map[string]any)["first_x"] = rows[0].(map[string]any)[x]
		out["coverage"].(map[string]any)["last_x"] = rows[len(rows)-1].(map[string]any)[x]
	}
	return encodeJSON(w, out, "")
}

// envelope returns the fields shared by every history object, with
// next_cursor set unless the run has exited and everything was read.
func (s *historyScan) envelope(warnings []string) (map[string]any, error) {
	stat, err := os.Stat(s.path)
	if err != nil {
		return nil, err
	}

	keys := sortedKeys(s.axes)
	skipped := make(map[string]any)
	for key := range s.nonNumeric {
		if _, ok := s.axes[key]; !ok {
			skipped[key] = "non_numeric"
		}
	}
	warnings = append(append([]string{}, s.warnings...), warnings...)
	if s.q.XAxis != "" && !s.xSeen && s.rowsScanned > 0 {
		warnings = append(warnings,
			fmt.Sprintf("x axis %q was not found in any row", s.q.XAxis))
	}
	seen := slices.AppendSeq(slices.Clone(keys), maps.Keys(s.nonNumeric))
	warnings = append(warnings, unmatchedKeyWarnings(s.q.Keys, seen)...)
	out := map[string]any{
		"schema": "leet.history/1",
		"source": querySource(s.path, s.run.GetEntity(), s.run.GetProject(), s.run.GetRunId()),
		"state": strings.ToLower(
			runState(s.exit, s.run != nil, stat.ModTime()).String(),
		),
		"exit_code":        nil,
		"run_id":           orNil(s.run.GetRunId()),
		"run_name":         orNil(s.run.GetDisplayName()),
		"requested_keys":   s.q.Keys,
		"keys":             keys,
		"axes":             maps.Clone(s.axes),
		"x_axis":           orNil(s.q.XAxis),
		"skipped_keys":     skipped,
		"exact":            !s.corrupt,
		"retrieval_method": "local_scan",
		"total_steps":      nil,
		"rows_scanned":     s.rowsScanned,
		"coverage": map[string]any{
			"first_x":            nil,
			"last_x":             nil,
			"requested_min_step": s.q.MinStep,
			"requested_max_step": s.q.MaxStep,
		},
		"next_cursor": nil,
		"warnings":    warnings,
	}
	if s.atEOF && s.maxStep >= 0 {
		out["total_steps"] = s.maxStep
	}
	if s.exit != nil {
		out["exit_code"] = s.exit.GetExitCode()
	}
	if !s.done() {
		out["next_cursor"] = encodeCursor(historyCursor{
			Version: 1,
			Offset:  s.offset,
			RunID:   s.run.GetRunId(),
			Size:    stat.Size(),
			Metrics: s.defs,
			MaxStep: s.maxStep,
		})
	}
	s.warnings, s.rowsScanned, s.corrupt = nil, 0, false
	return out, nil
}

func orNil(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// binSeries holds the points of one metric in file order.
type binSeries struct{ xs, ys []float64 }

func (s *historyScan) writeBins(w io.Writer) error {
	series := make(map[string]*binSeries)
	err := s.scan(func(h *spb.HistoryRecord) bool {
		if _, ok := s.rowValues(h); !ok {
			return true
		}
		for key, y := range s.values {
			if !s.selected(key) {
				continue
			}
			axis := s.axis(key)
			x, ok := s.values[axis]
			if !ok || !isFinite(x) {
				continue
			}
			s.axes[key] = axis
			ser := series[key]
			if ser == nil {
				ser = &binSeries{}
				series[key] = ser
			}
			ser.xs = append(ser.xs, x)
			ser.ys = append(ser.ys, y)
		}
		return true
	})
	if err != nil {
		return err
	}

	keys := slices.Sorted(maps.Keys(series))
	lo := make(map[string]float64, len(keys))
	hi := make(map[string]float64, len(keys))
	allLo, allHi := math.Inf(1), math.Inf(-1)
	sharedAxis := true
	for _, key := range keys {
		lo[key], hi[key] = slices.Min(series[key].xs), slices.Max(series[key].xs)
		allLo, allHi = min(allLo, lo[key]), max(allHi, hi[key])
		sharedAxis = sharedAxis && s.axes[key] == s.axes[keys[0]]
	}

	out, err := s.envelope(nil)
	if err != nil {
		return err
	}
	list := make([]any, 0, len(keys))
	for _, key := range keys {
		x0, x1 := lo[key], hi[key]
		if sharedAxis {
			x0, x1 = allLo, allHi
		}
		list = append(list, map[string]any{
			"key":    key,
			"x_axis": s.axes[key],
			"count":  len(series[key].xs),
			"bins":   bin(series[key].xs, series[key].ys, x0, x1, s.q.Bins),
		})
	}
	out["series"] = list
	out["truncated"] = false
	out["has_more"] = false
	if len(keys) > 0 && sharedAxis {
		out["coverage"].(map[string]any)["first_x"] = allLo
		out["coverage"].(map[string]any)["last_x"] = allHi
	}
	return encodeJSON(w, out, "")
}

// bin aggregates points into n equal-width bins over [lo, hi], each
// [x0, x1) with the last one closed, leaving out empty bins. min, max, avg
// and last cover the finite values of a bin and has_nan reports whether it
// held any other.
func bin(xs, ys []float64, lo, hi float64, n int) []any {
	type acc struct {
		count         int
		hasNaN        bool
		min, max, sum float64
		lastX, last   float64
	}
	accs := make([]acc, n)
	width := (hi - lo) / float64(n)
	for i, x := range xs {
		b := 0
		if width > 0 {
			b = min(int((x-lo)/width), n-1)
		}
		a, y := &accs[b], ys[i]
		if !isFinite(y) {
			a.hasNaN = true
			continue
		}
		if a.count == 0 || y < a.min {
			a.min = y
		}
		if a.count == 0 || y > a.max {
			a.max = y
		}
		if a.count == 0 || x >= a.lastX {
			a.lastX, a.last = x, y
		}
		a.sum += y
		a.count++
	}

	bins := make([]any, 0, n)
	for b, a := range accs {
		if a.count == 0 && !a.hasNaN {
			continue
		}
		x1 := hi
		if b < n-1 {
			x1 = lo + float64(b+1)*width
		}
		out := map[string]any{
			"x0":      lo + float64(b)*width,
			"x1":      x1,
			"count":   a.count,
			"has_nan": a.hasNaN,
			"min":     nil,
			"max":     nil,
			"avg":     nil,
			"last":    nil,
		}
		if a.count > 0 {
			out["min"], out["max"] = a.min, a.max
			out["avg"], out["last"] = a.sum/float64(a.count), a.last
		}
		bins = append(bins, out)
	}
	return bins
}
