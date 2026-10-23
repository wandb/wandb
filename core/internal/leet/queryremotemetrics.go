package leet

import (
	"cmp"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"maps"
	"math"
	"slices"
	"strings"
	"time"

	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhistoryreader"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/ffi"
)

// remoteHistoryWindow is how many steps one history read of a remote run
// covers.
const remoteHistoryWindow = 1000

// QueryRemoteHistory writes the leet.history/1 object of QueryHistory for
// the W&B run params names, read from the W&B server: its rows through
// the run's parquet export and live history, or its bins as the server
// aggregates them.
func QueryRemoteHistory(params *RemoteRunParams, q HistoryQuery, w io.Writer) error {
	clients, err := newRemoteClients(params.BaseURL, observability.NewNoOpLogger())
	if err != nil {
		return err
	}
	return queryRemoteHistory(clients, params, q, w)
}

// QueryRemoteSystem writes the leet.system/1 object of QuerySystem for the
// W&B run params names, read from the W&B server, which serves system
// metrics in bins only.
func QueryRemoteSystem(params *RemoteRunParams, q SystemQuery, w io.Writer) error {
	clients, err := newRemoteClients(params.BaseURL, observability.NewNoOpLogger())
	if err != nil {
		return err
	}
	return queryRemoteSystem(clients, params, q, w)
}

// remoteHistoryCursor is the step where the next page of remote history
// rows starts.
type remoteHistoryCursor struct {
	Version int    `json:"v"`
	Step    *int64 `json:"s"`
	RunID   string `json:"f"`
}

func queryRemoteHistory(
	c *remoteClients,
	params *RemoteRunParams,
	q HistoryQuery,
	w io.Writer,
) error {
	if err := q.validate(); err != nil {
		return err
	}
	if q.Follow {
		return errRemoteFollow
	}
	var start int64
	if q.MinStep != nil {
		start = *q.MinStep
	}
	if q.After != "" {
		var cur remoteHistoryCursor
		if err := decodeCursor(q.After, &cur); err != nil {
			return err
		}
		switch {
		case cur.Version != 1:
			return badRequest("after: unsupported cursor version")
		case cur.Step == nil:
			return badRequest("after: not a cursor from a previous call")
		case cur.RunID != params.RunID:
			return badRequest("after: the cursor is from another run")
		}
		start = max(start, *cur.Step)
	}
	info, err := c.runInfo(params)
	if err != nil {
		return err
	}
	r := &remoteHistory{
		c:          c,
		params:     params,
		q:          q,
		info:       info,
		axes:       make(map[string]string),
		nonNumeric: make(map[string]bool),
	}
	if q.Bins > 0 {
		return r.writeBins(w)
	}
	return r.writeRows(max(start, 0), w)
}

// remoteHistory builds the history object of one remote run.
type remoteHistory struct {
	c      *remoteClients
	params *RemoteRunParams
	q      HistoryQuery
	info   *RunInfo

	// axes is the x axis of every selected key seen with a numeric value.
	axes map[string]string
	// nonNumeric holds the selected keys seen without a numeric value.
	nonNumeric map[string]bool
	// xSeen is whether any row, or any bucket, held a value for q.XAxis.
	xSeen   bool
	scanned int
}

// selected reports whether key matches any of the requested keys.
func (r *remoteHistory) selected(key string) bool {
	return slices.ContainsFunc(r.q.Keys, func(p string) bool { return matchKey(p, key) })
}

// writeRows reads the rows of the steps from start up to the summary's
// _step, or q.MaxStep, in windows of remoteHistoryWindow steps until
// q.Limit rows are selected; with q.Last, the rows of the last q.Last
// steps. The next page of a running run starts after the last row the
// server returned.
func (r *remoteHistory) writeRows(start int64, w io.Writer) error {
	end := maxStepFromSummary(r.info.runSummary) + 1
	if r.q.MaxStep != nil {
		end = min(end, *r.q.MaxStep+1)
	}
	limit := cmp.Or(r.q.Limit, defaultHistoryLimit)
	if r.q.Last > 0 {
		start, limit = max(start, end-int64(r.q.Last)), r.q.Last
	}

	rows := []any{}
	next, last := start, start-1
	if next < end {
		ctx, cancel := remoteContext()
		defer cancel()
		reader, err := r.c.openHistory(ctx, r.params)
		if err != nil {
			if ctx.Err() != nil {
				return &QueryError{
					Code: "not_available",
					Message: "the run's history export did not download within 60 s;" +
						" pass --bins N to read the server's aggregates",
				}
			}
			return err
		}
		defer reader.Release()
	windows:
		for next < end {
			stop := min(next+remoteHistoryWindow, end)
			ctx, cancel := remoteContext()
			page, err := reader.GetHistorySteps(ctx, next, stop)
			cancel()
			if err != nil {
				return err
			}
			next = stop
			for _, kv := range page {
				r.scanned++
				last = kv.StepValue()
				row := r.row(kv)
				if row == nil {
					continue
				}
				rows = append(rows, row)
				if len(rows) == limit {
					next = last + 1
					break windows
				}
			}
		}
	}

	more := next < end
	if !more && r.info.runState.mayBeLive() {
		next = last + 1
	}
	out := r.envelope("remote_history", true)
	out["rows"] = rows
	out["truncated"] = more
	out["has_more"] = more
	if len(rows) > 0 {
		x := cmp.Or(r.q.XAxis, "_step")
		coverage := out["coverage"].(map[string]any)
		coverage["first_x"] = rows[0].(map[string]any)[x]
		coverage["last_x"] = rows[len(rows)-1].(map[string]any)[x]
	}
	if more || r.info.runState.mayBeLive() {
		out["next_cursor"] = encodeCursor(remoteHistoryCursor{
			Version: 1, Step: &next, RunID: r.params.RunID,
		})
	}
	return encodeJSON(w, out, "")
}

// row returns the selected numeric values of a history row with its _step,
// _runtime, _timestamp and the x axis, or nil when it has no selected
// value or no finite value for q.XAxis.
func (r *remoteHistory) row(kv parquet.KeyValueList) map[string]any {
	values := make(map[string]float64, len(kv))
	for _, item := range kv {
		switch v := item.Value.(type) {
		case float64:
			values[item.Key] = v
		case int64:
			values[item.Key] = float64(v)
		case uint64:
			values[item.Key] = float64(v)
		case nil:
		default:
			if r.selected(item.Key) {
				r.nonNumeric[item.Key] = true
			}
		}
	}
	if r.q.XAxis != "" {
		x, ok := values[r.q.XAxis]
		r.xSeen = r.xSeen || ok
		if !ok || !isFinite(x) {
			return nil
		}
	}

	var row map[string]any
	for key, v := range values {
		if !r.selected(key) {
			continue
		}
		if row == nil {
			row = make(map[string]any)
		}
		row[key] = v
		r.axes[key] = cmp.Or(r.q.XAxis, "_step")
	}
	if row == nil {
		return nil
	}
	row["_step"] = kv.StepValue()
	for _, key := range []string{"_runtime", "_timestamp", r.q.XAxis} {
		if v, ok := values[key]; ok && key != "" {
			row[key] = v
		}
	}
	return row
}

// writeBins asks the server for about q.Bins buckets of every selected
// numeric summary key over the x axis, between q.MinStep and q.MaxStep.
func (r *remoteHistory) writeBins(w io.Writer) error {
	x := cmp.Or(r.q.XAxis, "_step")
	var keys []string
	for key, v := range r.info.runSummary {
		if !r.selected(key) {
			continue
		}
		switch v.(type) {
		case float64, int64, uint64:
			keys = append(keys, key)
		default:
			r.nonNumeric[key] = true
		}
	}
	slices.Sort(keys)
	specKeys := []string{x}
	for _, key := range keys {
		if key != x {
			specKeys = append(specKeys, key)
		}
	}

	spec := map[string]any{"keys": specKeys, "bins": r.q.Bins, "xAxis": x}
	if r.q.MinStep != nil {
		spec["minStep"] = *r.q.MinStep
	}
	if r.q.MaxStep != nil {
		spec["maxStep"] = *r.q.MaxStep
	}
	var buckets []any
	if len(keys) > 0 {
		var err error
		if buckets, err = r.c.bucketedHistory(r.params, spec); err != nil {
			return err
		}
	}

	series, lo, hi, rows := remoteSeries(buckets, x, keys)
	for _, entry := range series {
		r.axes[entry.(map[string]any)["key"].(string)] = x
	}
	r.scanned, r.xSeen = rows, lo <= hi
	out := r.envelope("remote_bucketed", false)
	out["series"] = series
	out["truncated"] = false
	out["has_more"] = false
	if lo <= hi {
		coverage := out["coverage"].(map[string]any)
		coverage["first_x"], coverage["last_x"] = lo, hi
	}
	return encodeJSON(w, out, "")
}

// envelope returns the fields shared by the rows and bins objects.
func (r *remoteHistory) envelope(method string, exact bool) map[string]any {
	skipped := make(map[string]any)
	for key := range r.nonNumeric {
		if _, ok := r.axes[key]; !ok {
			skipped[key] = "non_numeric"
		}
	}
	seen := slices.AppendSeq(slices.Collect(maps.Keys(r.axes)), maps.Keys(r.nonNumeric))
	warnings := []string{}
	if r.info.definesMetrics() {
		warnings = append(warnings, "define_metric step metrics are not applied to remote runs")
	}
	if r.q.XAxis != "" && !r.xSeen && (r.scanned > 0 || r.info.runSummary[r.q.XAxis] == nil) {
		warnings = append(warnings, fmt.Sprintf("x axis %q was not found in any row", r.q.XAxis))
	}
	warnings = append(warnings, unmatchedKeyWarnings(r.q.Keys, seen)...)
	out := map[string]any{
		"schema":           "leet.history/1",
		"source":           r.params.remoteSource(r.params.RunID),
		"state":            strings.ToLower(r.info.runState.String()),
		"state_detail":     r.info.state,
		"exit_code":        nil,
		"run_id":           r.info.runId,
		"run_name":         orNil(r.info.displayName),
		"requested_keys":   r.q.Keys,
		"keys":             sortedKeys(r.axes),
		"axes":             r.axes,
		"x_axis":           orNil(r.q.XAxis),
		"skipped_keys":     skipped,
		"exact":            exact,
		"retrieval_method": method,
		"total_steps":      nil,
		"rows_scanned":     r.scanned,
		"coverage": map[string]any{
			"first_x":            nil,
			"last_x":             nil,
			"requested_min_step": r.q.MinStep,
			"requested_max_step": r.q.MaxStep,
		},
		"next_cursor": nil,
		"warnings":    warnings,
	}
	if total := maxStepFromSummary(r.info.runSummary); total >= 0 {
		out["total_steps"] = total
	}
	return out
}

// definesMetrics reports whether the run's config carries define_metric
// rules under _wandb.m.
func (ri *RunInfo) definesMetrics() bool {
	for _, item := range ri.config.GetUpdate() {
		if item.GetKey() != "_wandb" {
			continue
		}
		wb, _ := simplejsonext.UnmarshalObjectString(item.GetValueJson())
		rules, _ := wb["m"].([]any)
		return len(rules) > 0
	}
	return false
}

// openHistory opens the history of the run params names, its parquet
// export and its live rows, for GetHistorySteps.
func (c *remoteClients) openHistory(
	ctx context.Context,
	params *RemoteRunParams,
) (historyStepReader, error) {
	if c.arrow == nil {
		var err error
		if c.arrow, err = ffi.NewRustArrowWrapper(); err != nil {
			return nil, err
		}
	}
	return runhistoryreader.New(ctx, params.Entity, params.Project, params.RunID,
		c.graphql, c.http, nil, false, c.arrow)
}

// bucketedHistory sends one bucketedHistory spec for the run params names
// and returns its buckets.
func (c *remoteClients) bucketedHistory(
	params *RemoteRunParams,
	spec map[string]any,
) ([]any, error) {
	specJSON, err := json.Marshal(spec)
	if err != nil {
		return nil, err
	}
	ctx, cancel := remoteContext()
	defer cancel()
	response, err := gql.QueryRunBucketedHistory(ctx, c.graphql,
		params.Entity, params.Project, params.RunID, []string{string(specJSON)})
	if err != nil {
		return nil, err
	}
	if response == nil || response.Project == nil || response.Project.Run == nil {
		return nil, &QueryError{
			Code: "run_not_found",
			Message: fmt.Sprintf("run %q not found in %s/%s",
				params.RunID, params.Entity, params.Project),
		}
	}
	if len(response.Project.Run.BucketedHistory) == 0 {
		return nil, nil
	}
	buckets, _ := response.Project.Run.BucketedHistory[0].([]any)
	return buckets, nil
}

// remoteSeries maps the buckets of one bucketedHistory spec, x first in
// its keys, to one series per key with a bin in the shape of bin(), with
// the x range of the kept bins (lo > hi when none) and the rows the
// buckets hold.
func remoteSeries(
	buckets []any,
	x string,
	keys []string,
) (series []any, lo, hi float64, rows int) {
	lo, hi = math.Inf(1), math.Inf(-1)
	for _, bucket := range buckets {
		fields, _ := bucket.(map[string]any)
		size, _ := fields["bucketSize"].(float64)
		rows += int(size)
	}
	series = make([]any, 0, len(keys))
	for _, key := range keys {
		bins := []any{}
		total := 0
		for _, bucket := range buckets {
			fields, _ := bucket.(map[string]any)
			x0, ok0 := fields[x+"Min"].(float64)
			x1, ok1 := fields[x+"Max"].(float64)
			hasNaN, _ := fields[key+"HasNaN"].(bool)
			if !ok0 || !ok1 || (fields[key+"Avg"] == nil && !hasNaN) {
				continue
			}
			lo, hi = min(lo, x0), max(hi, x1)
			n := 0
			if c, ok := fields[key+"Count"].(float64); ok {
				n = int(c)
			} else if fields[key+"Avg"] != nil {
				n = 1
			}
			total += n
			bins = append(bins, map[string]any{
				"x0":      x0,
				"x1":      x1,
				"count":   n,
				"has_nan": hasNaN,
				"min":     fields[key+"Min"],
				"max":     fields[key+"Max"],
				"avg":     fields[key+"Avg"],
				"last":    fields[key+"Last"],
			})
		}
		if len(bins) == 0 {
			continue
		}
		series = append(series, map[string]any{
			"key": key, "x_axis": x, "count": total, "bins": bins,
		})
	}
	return series, lo, hi, rows
}

func queryRemoteSystem(
	c *remoteClients,
	params *RemoteRunParams,
	q SystemQuery,
	w io.Writer,
) error {
	if err := q.validate(); err != nil {
		return err
	}
	if q.Bins == 0 {
		return &QueryError{
			Code:    "not_available",
			Message: "system metrics of a remote run are served in bins only: pass --bins N",
		}
	}
	since, sinceAgo, err := parseSince(q.Since)
	if err != nil {
		return err
	}
	info, err := c.runInfo(params)
	if err != nil {
		return err
	}
	if sinceAgo > 0 {
		end := time.Now()
		if !info.runState.mayBeLive() && !info.heartbeatAt.IsZero() {
			end = info.heartbeatAt
		}
		since = end.Add(-sinceAgo)
	}

	var keys, known []string
	for _, key := range info.systemMetricKeys() {
		name := systemKeyPrefix + strings.TrimPrefix(key, "system/")
		known = append(known, name)
		if len(q.Keys) == 0 ||
			slices.ContainsFunc(q.Keys, func(p string) bool { return matchKey(p, name) }) {
			keys = append(keys, key)
		}
	}
	spec := map[string]any{
		"keys":  append([]string{"_timestamp"}, keys...),
		"bins":  q.Bins,
		"xAxis": "_timestamp",
	}
	if !since.IsZero() {
		spec["minX"] = since.Unix()
	}
	var buckets []any
	if len(keys) > 0 {
		if buckets, err = c.bucketedHistory(params, spec); err != nil {
			return err
		}
	}

	series, lo, hi, rows := remoteSeries(buckets, "_timestamp", keys)
	names := make([]string, 0, len(series))
	for _, entry := range series {
		entry := entry.(map[string]any)
		name := systemKeyPrefix + strings.TrimPrefix(entry["key"].(string), "system/")
		entry["key"] = name
		entry["title"], entry["unit"] = systemMetricTitleUnit(name)
		names = append(names, name)
	}
	requested := q.Keys
	if requested == nil {
		requested = []string{}
	}
	out := map[string]any{
		"schema":           "leet.system/1",
		"source":           params.remoteSource(params.RunID),
		"state":            strings.ToLower(info.runState.String()),
		"state_detail":     info.state,
		"exit_code":        nil,
		"run_id":           info.runId,
		"run_name":         orNil(info.displayName),
		"requested_keys":   requested,
		"keys":             names,
		"x_axis":           "_timestamp",
		"skipped_keys":     map[string]any{},
		"exact":            false,
		"retrieval_method": "remote_bucketed",
		"rows_scanned":     rows,
		"coverage": map[string]any{
			"first_x":         nil,
			"last_x":          nil,
			"requested_since": rfc3339OrNil(since),
		},
		"series":      series,
		"truncated":   false,
		"has_more":    false,
		"next_cursor": nil,
		"warnings":    unmatchedKeyWarnings(q.Keys, known),
	}
	if lo <= hi {
		coverage := out["coverage"].(map[string]any)
		coverage["first_x"], coverage["last_x"] = lo, hi
	}
	return encodeJSON(w, out, "")
}
