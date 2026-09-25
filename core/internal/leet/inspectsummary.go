package leet

import (
	"errors"
	"fmt"
	"io"
	"os"
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
		path:      path,
		lastWrite: stat.ModTime(),
		overview:  NewRunOverview(),
		console:   NewRunConsoleLogs(),
		lastStep:  -1,
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
		if step, ok := historyStep(rec.History); ok {
			d.lastStep = max(d.lastStep, step)
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
	age := time.Since(d.lastWrite).Round(time.Second)
	var detail string
	switch {
	case d.exit != nil:
		d.overview.SetRunState(runStateForExitCode(d.exit.GetExitCode()))
		detail = fmt.Sprintf("exit code %d", d.exit.GetExitCode())
	case d.run.ID == "":
		d.overview.SetRunState(RunStateUnknown)
		detail = "no run record yet"
	case age > RunCrashTimeout:
		d.overview.SetRunState(RunStateCrashed)
		detail = fmt.Sprintf("no exit record, last write %v ago", age)
	default:
		d.overview.SetRunState(RunStateRunning)
		detail = fmt.Sprintf("last write %v ago", age)
	}
	return strings.ToLower(d.overview.StateString()), detail
}

// consoleTail returns the last console lines and the total line count.
func (d *runDigest) consoleTail() ([]ConsoleLogLine, int) {
	lines := d.console.lines
	return lines[max(len(lines)-summaryConsoleLines, 0):], len(lines)
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

	tail, total := d.consoleTail()
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
	state, _ := d.state()

	summary := d.overview.runSummary.ToNestedMaps()
	delete(summary, "_wandb")
	config := d.overview.runConfig.CloneTree()
	delete(config, "_wandb")

	tail, total := d.consoleTail()
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

	out := map[string]any{
		"file":          d.path,
		"run_id":        d.run.ID,
		"name":          d.run.DisplayName,
		"entity":        d.run.Entity,
		"project":       d.run.Project,
		"notes":         d.run.Notes,
		"tags":          append([]string{}, d.run.Tags...),
		"state":         state,
		"last_write":    d.lastWrite.UTC(),
		"summary":       summary,
		"config":        config,
		"console":       console,
		"console_lines": total,
		"start_time":    nil,
		"exit_code":     nil,
		"step":          nil,
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

	return encodeJSON(w, out, "  ")
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
