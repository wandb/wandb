package leet

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// summaryConsoleLines is how many of the last console lines
	// PrintSummary shows.
	summaryConsoleLines = 20

	// summaryQueryConsoleLines is how many of the last console lines
	// QuerySummary returns.
	summaryQueryConsoleLines = 50

	// summaryKeyWidth caps the key column width in PrintSummary's text
	// output, so one long key does not push every value off screen.
	summaryKeyWidth = 40

	// summaryListWidth caps lists, which PrintSummary's text output shows
	// inline as JSON.
	summaryListWidth = 80
)

// PrintSummary writes an overview of a run read from its .wandb file: its
// name and ID, state, last step, the latest values of its metrics, its
// config and the end of its console output, as text or as one JSON object.
// An empty runFile resolves to the latest run in wandbDir.
func PrintSummary(runFile, wandbDir string, w io.Writer, asJSON bool) error {
	path, err := resolveWandbFile(runFile, wandbDir)
	if err != nil {
		return err
	}

	digest, err := readRunDigest(path)
	if err != nil {
		return err
	}

	sessionFeatures.mark("inspector.summary")
	if asJSON {
		return digest.writeJSON(w)
	}
	return digest.writeText(w)
}

// SummaryQuery selects what QuerySummary reports about a run.
type SummaryQuery struct {
	Keys []string `json:"keys" doc:"Summary and history keys or globs with * and ? to report, e.g. val/* or train/loss. A glob never matches keys starting with _."`
}

// QuerySummary writes an overview of a run as one JSON object with the
// schema leet.summary/1: what PrintSummary writes as JSON, the keys the
// run logged to its history with how often, the last value and the last
// step of each, and the last console lines in the shape of QueryConsole.
// q.Keys, keys or globs, select the summary values and history keys. The
// object has no paging: next_cursor is always null and has_more false.
//
// The run is runFile when given, else the run in wandbDir that run names,
// else the newest run in wandbDir, as resolveQueryRun decides.
func QuerySummary(wandbDir, runFile, run string, q SummaryQuery, w io.Writer) error {
	path, err := resolveQueryRun(wandbDir, runFile, run)
	if err != nil {
		return err
	}
	if path, err = filepath.Abs(path); err != nil {
		return err
	}
	digest, err := readRunDigest(path)
	if err != nil {
		return err
	}
	return digest.writeQueryJSON(w, q.Keys)
}

// runDigest is what PrintSummary reports about a run.
type runDigest struct {
	path      string
	lastWrite time.Time

	run      RunMsg
	overview *RunOverview
	console  *RunConsoleLogs
	exit     *spb.RunExitRecord

	// lastStep is the highest history step, or -1 without history.
	lastStep int64

	// historyKeys holds every key logged to the history by name.
	historyKeys map[string]*historyKey
}

// historyKey is what the history of a run holds for one key.
type historyKey struct {
	// count is how many history records held the key.
	count int
	// last is the key's item in the last of them.
	last *spb.HistoryItem
	// lastStep is the step of the last record that held the key.
	lastStep int64
}

func readRunDigest(path string) (*runDigest, error) {
	stat, err := os.Stat(path)
	if err != nil {
		return nil, err
	}

	reader, err := transactionlog.OpenReader(path, observability.NewNoOpLogger())
	if err != nil {
		return nil, err
	}
	defer reader.Close()

	d := &runDigest{
		path:        path,
		lastWrite:   stat.ModTime(),
		overview:    NewRunOverview(),
		console:     NewRunConsoleLogs(),
		lastStep:    -1,
		historyKeys: make(map[string]*historyKey),
	}
	for {
		record, err := readRecord(reader)
		switch {
		case errors.Is(err, io.EOF), errors.Is(err, io.ErrUnexpectedEOF):
			return d, nil
		case errors.Is(err, errCorruptSkipped):
			continue
		case err != nil:
			return nil, err
		}
		d.apply(record)
	}
}

func (d *runDigest) apply(record *spb.Record) {
	switch rec := record.RecordType.(type) {
	case *spb.Record_Run:
		d.run = runMsgFromRecord(d.path, rec.Run)
		d.overview.ProcessRunMsg(d.run)
	case *spb.Record_Config:
		d.overview.runConfig.ApplyChangeRecord(rec.Config, func(error) {})
	case *spb.Record_Summary:
		d.overview.ProcessSummaryMsg([]*spb.SummaryRecord{rec.Summary})
	case *spb.Record_History:
		step, ok := historyStep(rec.History)
		if !ok {
			return
		}
		d.lastStep = max(d.lastStep, step)
		for _, item := range rec.History.GetItem() {
			if _, _, ok := historyMediaField(item); ok {
				continue
			}
			key := historyItemKey(item)
			if key == "" {
				continue
			}
			hk := d.historyKeys[key]
			if hk == nil {
				hk = &historyKey{}
				d.historyKeys[key] = hk
			}
			hk.count++
			hk.last, hk.lastStep = item, step
		}
	case *spb.Record_OutputRaw:
		msg := parseOutputRaw(d.path, rec.OutputRaw).(ConsoleLogMsg)
		d.console.ProcessRaw(msg.Text, msg.IsStderr, msg.Time)
	case *spb.Record_Exit:
		d.exit = rec.Exit
	}
}

// state returns the run's state and a short explanation of it.
//
// Without an exit record, a run is presumed crashed once its file has not
// changed for RunCrashTimeout, as in the TUI.
func (d *runDigest) state() (string, string) {
	state, detail := runStateDetail(d.exit, d.run.ID != "", d.lastWrite)
	d.overview.SetRunState(state)
	return strings.ToLower(state.String()), detail
}

// runStateDetail returns the state of a run read from its file, as
// runState decides, and a short explanation of it.
func runStateDetail(
	exit *spb.RunExitRecord,
	haveRun bool,
	lastWrite time.Time,
) (RunState, string) {
	state := runState(exit, haveRun, lastWrite)
	age := time.Since(lastWrite).Round(time.Second)
	var detail string
	switch {
	case exit != nil:
		detail = fmt.Sprintf("exit code %d", exit.GetExitCode())
	case state == RunStateUnknown:
		detail = "no run record yet"
	case state == RunStateCrashed:
		detail = fmt.Sprintf("no exit record, last write %v ago", age)
	default:
		detail = fmt.Sprintf("last write %v ago", age)
	}
	return state, detail
}

// runState returns the state of a run read from its file: from its exit
// record, else unknown without a run record, else crashed once the file
// has gone RunCrashTimeout without a write, else running.
func runState(exit *spb.RunExitRecord, haveRun bool, lastWrite time.Time) RunState {
	switch {
	case exit != nil:
		return runStateForExitCode(exit.GetExitCode())
	case !haveRun:
		return RunStateUnknown
	case time.Since(lastWrite) > RunCrashTimeout:
		return RunStateCrashed
	default:
		return RunStateRunning
	}
}

// consoleTail returns the last n console lines and the total line count.
func (d *runDigest) consoleTail(n int) ([]ConsoleLogLine, int) {
	lines := d.console.lines
	return lines[max(len(lines)-n, 0):], len(lines)
}

func (d *runDigest) writeText(w io.Writer) error {
	state, detail := d.state()

	run := d.run.ID
	if d.run.DisplayName != "" {
		run = d.run.DisplayName + " (" + d.run.ID + ")"
	}

	var b strings.Builder
	header := [][2]string{
		{"run", run},
		{"project", strings.Trim(d.run.Entity+"/"+d.run.Project, "/")},
		{"file", d.path},
		{"state", state + " (" + detail + ")"},
	}
	if !d.run.StartTime.IsZero() {
		header = append(header, [2]string{"started", d.run.StartTime.Local().Format(time.RFC3339)})
	}
	if d.lastStep >= 0 {
		header = append(header, [2]string{"step", fmt.Sprint(d.lastStep)})
	}
	for _, kv := range header {
		fmt.Fprintf(&b, "%-8s %s\n", kv[0], kv[1])
	}

	writeTextSection(&b, "summary", d.overview.runSummary.ToNestedMaps())
	writeTextSection(&b, "config", d.overview.runConfig.CloneTree())

	tail, total := d.consoleTail(summaryConsoleLines)
	if total > 0 {
		fmt.Fprintf(&b, "\nconsole (last %d of %d lines)\n", len(tail), total)
	}
	for _, line := range tail {
		stream := ""
		if line.IsStderr {
			stream = "[stderr] "
		}
		fmt.Fprintf(&b, "  %s  %s%s\n",
			line.Timestamp.Local().Format(consoleTimestampFormat), stream, line.Content)
	}

	_, err := io.WriteString(w, b.String())
	return err
}

// writeTextSection writes a titled list of the tree's values, leaving out
// W&B's internal "_wandb" entries.
func writeTextSection(b *strings.Builder, title string, tree map[string]any) {
	var items []KeyValuePair
	flattenMap(compactValue(tree).(map[string]any), "", &items, nil)

	var shown []KeyValuePair
	width := 0
	for _, kv := range items {
		if len(kv.Path) > 0 && kv.Path[0] == "_wandb" {
			continue
		}
		shown = append(shown, kv)
		width = min(max(width, len(kv.Key)), summaryKeyWidth)
	}
	if len(shown) == 0 {
		return
	}

	fmt.Fprintf(b, "\n%s\n", title)
	for _, kv := range shown {
		fmt.Fprintf(b, "  %-*s  %s\n", width, kv.Key, kv.Value)
	}
}

func (d *runDigest) writeJSON(w io.Writer) error {
	out, _ := d.jsonFields()

	tail, total := d.consoleTail(summaryConsoleLines)
	console := make([]map[string]any, 0, len(tail))
	for _, line := range tail {
		stream := "stdout"
		if line.IsStderr {
			stream = "stderr"
		}
		console = append(console, map[string]any{
			"time":   line.Timestamp.UTC(),
			"stream": stream,
			"line":   line.Content,
		})
	}
	out["console"] = console
	out["console_lines"] = total

	return encodeJSON(w, out, "  ")
}

// writeQueryJSON writes the leet.summary/1 object of QuerySummary, with
// the summary values and history keys that keys select, or all of them
// when keys is empty, and a warning for each pattern that selects nothing.
func (d *runDigest) writeQueryJSON(w io.Writer, keys []string) error {
	out, detail := d.jsonFields()

	matched := make([]bool, len(keys))
	selected := func(key string) bool {
		hit := len(keys) == 0
		for i, p := range keys {
			if matchKey(p, key) {
				matched[i], hit = true, true
			}
		}
		return hit
	}
	out["summary"] = selectTree(out["summary"].(map[string]any), "", selected)
	historyKeys := make(map[string]any, len(d.historyKeys))
	for key, hk := range d.historyKeys {
		if selected(key) {
			historyKeys[key] = map[string]any{
				"count":     hk.count,
				"last":      historyItemValue(hk.last),
				"last_step": hk.lastStep,
			}
		}
	}
	warnings := []string{}
	for i, pattern := range keys {
		if !matched[i] {
			warnings = append(warnings, fmt.Sprintf("no key matches %q", pattern))
		}
	}

	tail, total := d.consoleTail(summaryQueryConsoleLines)
	console := make([]any, 0, len(tail))
	for i, line := range tail {
		console = append(console, consoleLineJSON(total-len(tail)+i, line))
	}

	out["schema"] = "leet.summary/1"
	out["source"] = querySource(d.path, d.run.Entity, d.run.Project, d.run.ID)
	out["state_detail"] = detail
	out["history_keys"] = historyKeys
	out["console"] = console
	out["console_lines"] = total
	out["warnings"] = warnings
	out["truncated"] = false
	out["has_more"] = false
	out["next_cursor"] = nil

	return encodeJSON(w, out, "")
}

// selectTree returns the entries of tree, a nested map whose dotted paths
// start with prefix, that selected keeps: a value whose path it selects,
// or a map holding one.
func selectTree(tree map[string]any, prefix string, selected func(string) bool) map[string]any {
	out := make(map[string]any, len(tree))
	for key, v := range tree {
		path := prefix + key
		if selected(path) {
			out[key] = v
		} else if sub, ok := v.(map[string]any); ok {
			if sub = selectTree(sub, path+".", selected); len(sub) > 0 {
				out[key] = sub
			}
		}
	}
	return out
}

// historyItemValue returns the item's value: its typed number, boolean,
// null or text, a text that parses as a number as that number, else its
// decoded JSON, or the JSON text when it does not decode.
func historyItemValue(item *spb.HistoryItem) any {
	switch value := item.GetValue().(type) {
	case *spb.HistoryItem_Number:
		return value.Number
	case *spb.HistoryItem_Integer:
		return value.Integer
	case *spb.HistoryItem_Text:
		if v, ok := historyItemFloat(item); ok {
			return v
		}
		return value.Text
	case *spb.HistoryItem_Boolean:
		return value.Boolean
	case *spb.HistoryItem_None:
		return nil
	}
	s := cmp.Or(item.GetJson(), item.GetValueJson())
	if v, err := simplejsonext.UnmarshalString(s); err == nil {
		return v
	}
	return s
}

// jsonFields returns the run's identity, state, summary and config as
// writeJSON reports them, without the console, and the explanation of
// the run's state.
func (d *runDigest) jsonFields() (map[string]any, string) {
	state, detail := d.state()

	summary := d.overview.runSummary.ToNestedMaps()
	delete(summary, "_wandb")
	config := d.overview.runConfig.CloneTree()
	delete(config, "_wandb")

	out := map[string]any{
		"file":       d.path,
		"run_id":     d.run.ID,
		"name":       d.run.DisplayName,
		"entity":     d.run.Entity,
		"project":    d.run.Project,
		"notes":      d.run.Notes,
		"tags":       append([]string{}, d.run.Tags...),
		"state":      state,
		"last_write": d.lastWrite.UTC(),
		"summary":    summary,
		"config":     config,
		"start_time": nil,
		"exit_code":  nil,
		"step":       nil,
	}
	if !d.run.StartTime.IsZero() {
		out["start_time"] = d.run.StartTime.UTC()
	}
	if d.exit != nil {
		out["exit_code"] = d.exit.GetExitCode()
	}
	if d.lastStep >= 0 {
		out["step"] = d.lastStep
	}
	return out, detail
}

// compactValue replaces each W&B data type such as a histogram or an image,
// which is a map with a "_type" key, with one "type path" string, and each
// list with its JSON, truncated.
//
// The result is a new tree: the summary can hold its values by reference.
func compactValue(v any) any {
	switch v := v.(type) {
	case map[string]any:
		if typ, ok := v["_type"].(string); ok {
			path, _ := v["path"].(string)
			return strings.TrimSpace(typ + " " + path)
		}
		out := make(map[string]any, len(v))
		for k, e := range v {
			out[k] = compactValue(e)
		}
		return out
	case []any:
		s, _ := simplejsonext.MarshalToString(v)
		return truncateValue(s, summaryListWidth)
	}
	return v
}
