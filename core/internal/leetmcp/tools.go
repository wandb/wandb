package leetmcp

import (
	"bytes"
	"cmp"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"

	"github.com/wandb/wandb/core/internal/leet"
)

// tool is one MCP tool: a wandb leet verb.
type tool struct {
	name        string
	description string

	// options is the zero value of the verb's options struct, whose fields
	// are the tool's inputs besides path and run.
	options any

	// perRun is whether the tool reads one run and takes the run input.
	perRun bool

	// required names the inputs a call must give.
	required []string

	// readOnly is whether the tool changes nothing, for the readOnlyHint
	// annotation.
	readOnly bool

	// run writes the tool's JSON object to w, or returns the error to
	// report as a leet.error/1 object.
	run func(args json.RawMessage, w io.Writer) error
}

var tools = []tool{
	{
		name: "leet_runs",
		description: "List the runs of a local wandb directory as JSON, newest first, with" +
			" each run's ID, name, project, state, exit code, last step, tags and notes," +
			" whether LEET has it selected or pinned and, with summary_keys, its latest" +
			" summary values. A run directory or .wandb file lists that one run.",
		options:  leet.RunsQuery{},
		readOnly: true,
		run: func(args json.RawMessage, w io.Writer) error {
			var q leet.RunsQuery
			src, err := decodeArguments(args, &q, false)
			if err != nil {
				return err
			}
			return leet.ListRuns(src.path, "", q, w)
		},
	},
	{
		name: "leet_history",
		description: "The metric series of a run from its local .wandb file as JSON: the" +
			" logged rows of the selected keys, or with bins their min, max, average and" +
			" last value per equal-width bin. When more rows exist than one call returns," +
			" pass next_cursor back as after.",
		options:  leet.HistoryQuery{},
		perRun:   true,
		required: []string{"keys"},
		readOnly: true,
		run:      perRun(leet.QueryHistory),
	},
	{
		name: "leet_summary",
		description: "A run's state, exit code, last step, latest metrics, config, the keys" +
			" it logged with their count, last value and last step, and its last 50" +
			" console lines as JSON.",
		options:  leet.SummaryQuery{},
		perRun:   true,
		readOnly: true,
		run:      perRun(leet.QuerySummary),
	},
	{
		name: "leet_console",
		description: "The console output of a run as JSON with ANSI escapes stripped: grep" +
			" and since select lines, last keeps the last N of them, and limit with after" +
			" pages through them from the start.",
		options:  leet.ConsoleQuery{},
		perRun:   true,
		readOnly: true,
		run:      perRun(leet.QueryConsole),
	},
	{
		name: "leet_system",
		description: "The system metrics of a run (CPU, memory, GPU, disk, network) as" +
			" JSON: samples over time, or with bins their min, max, average and last value" +
			" per bin with each metric's title and unit. Keys carry the system. prefix.",
		options:  leet.SystemQuery{},
		perRun:   true,
		readOnly: true,
		run:      perRun(leet.QuerySystem),
	},
	{
		name: "leet_session",
		description: "Steer the LEET a user has open on a wandb directory: select, pin or" +
			" open runs, set a filter, focus a chart, put the crosshair on a step, press a" +
			" key binding by name, or report what it shows with status. Fails with" +
			" no_session when no LEET shows the directory.",
		options:  sessionOptions{},
		required: []string{"method"},
		run:      runSession,
	},
}

// followInputs are the options of the follow mode of a verb, which a tool
// never uses: a result is one object.
var followInputs = []string{"follow", "idle_timeout"}

// pathDoc documents the path input of every tool.
const pathDoc = "Wandb directory, run directory or .wandb file. Defaults to the wandb" +
	" directory under $WANDB_DIR or the working directory. Run URLs come in a later release."

// controlMethod is a method of the control channel, for the method enum of
// the leet_session schema.
type controlMethod string

// sessionOptions are the inputs of leet_session besides path.
type sessionOptions struct {
	Method controlMethod   `json:"method" doc:"What LEET should do or report."`
	Params json.RawMessage `json:"params" doc:"The parameters of the method as an object, e.g. {\"filter\": \"cfg.lr>=0.001\"} for runs.select."`
}

// source is the run a tool call reads: the path of its wandb directory, run
// directory or .wandb file, and the run selected within a directory.
type source struct{ path, run string }

// decodeArguments splits the arguments of a tool call into the source and
// the options struct options points to, rejecting inputs the tool does not
// take.
func decodeArguments(args json.RawMessage, options any, perRun bool) (source, error) {
	var src source
	fields := make(map[string]json.RawMessage)
	if len(args) > 0 && json.Unmarshal(args, &fields) != nil {
		return src, badRequest("arguments must be an object")
	}
	inputs := map[string]*string{"path": &src.path}
	if perRun {
		inputs["run"] = &src.run
	}
	for name, dst := range inputs {
		if raw, ok := fields[name]; ok {
			if json.Unmarshal(raw, dst) != nil {
				return src, badRequest("%s has the wrong type", name)
			}
			delete(fields, name)
		}
	}
	for _, name := range followInputs {
		if _, ok := fields[name]; ok {
			return src, badRequest("%s is not available to a tool: call again for new rows", name)
		}
	}
	rest, _ := json.Marshal(fields)
	dec := json.NewDecoder(bytes.NewReader(rest))
	dec.DisallowUnknownFields()
	if err := dec.Decode(options); err != nil {
		var typeErr *json.UnmarshalTypeError
		if errors.As(err, &typeErr) {
			return src, badRequest("%s has the wrong type", typeErr.Field)
		}
		return src, badRequest("%s", strings.TrimPrefix(err.Error(), "json: "))
	}

	switch {
	case src.path == "":
		src.path = defaultPath()
	case strings.HasPrefix(src.path, "http://"), strings.HasPrefix(src.path, "https://"):
		return src, &leet.QueryError{
			Code:    "not_available",
			Message: "remote runs come in a later release",
		}
	}
	if path, err := filepath.EvalSymlinks(src.path); err == nil {
		src.path = path
	}
	return src, nil
}

// defaultPath is the wandb directory of the working directory, or of
// $WANDB_DIR, as wandb.init writes it.
func defaultPath() string {
	root := cmp.Or(os.Getenv("WANDB_DIR"), ".")
	if info, err := os.Stat(filepath.Join(root, ".wandb")); err == nil && info.IsDir() {
		return filepath.Join(root, ".wandb")
	}
	return filepath.Join(root, "wandb")
}

func badRequest(format string, args ...any) error {
	return &leet.QueryError{Code: "bad_request", Message: fmt.Sprintf(format, args...)}
}

// perRun adapts a query of one run to a tool's run function.
func perRun[Q any](
	query func(wandbDir, runFile, run string, q Q, w io.Writer) error,
) func(json.RawMessage, io.Writer) error {
	return func(args json.RawMessage, w io.Writer) error {
		var q Q
		src, err := decodeArguments(args, &q, true)
		if err != nil {
			return err
		}
		return query(src.path, "", src.run, q, w)
	}
}

// runSession sends a request to the LEET showing the wandb directory of
// the path and writes its result. An error reply is a bad_request, or
// not_available while LEET waits for user input.
func runSession(args json.RawMessage, w io.Writer) error {
	var o sessionOptions
	src, err := decodeArguments(args, &o, false)
	if err != nil {
		return err
	}
	if _, err := os.Stat(src.path); err != nil {
		return err
	}
	if file := leet.QueryRunFile(src.path, ""); file != "" {
		src.path = filepath.Dir(filepath.Dir(file))
	}
	if len(o.Params) == 0 {
		o.Params = json.RawMessage("{}")
	}
	request, _ := json.Marshal(map[string]any{
		"jsonrpc": "2.0", "id": 1, "method": o.Method, "params": o.Params,
	})
	var reply bytes.Buffer
	err = leet.SessionRequest(src.path, string(request), &reply)
	if err != nil && !errors.Is(err, leet.ErrSessionReplyError) {
		return err
	}
	var parsed struct {
		Result json.RawMessage    `json:"result"`
		Error  *leet.ControlError `json:"error"`
	}
	if err := json.Unmarshal(reply.Bytes(), &parsed); err != nil {
		return err
	}
	if parsed.Error != nil {
		code := "bad_request"
		switch parsed.Error.Code {
		case -32000:
			code = "internal"
		case -32001:
			code = "not_available"
		}
		return &leet.QueryError{Code: code, Message: parsed.Error.Message}
	}
	_, err = w.Write(parsed.Result)
	return err
}

// ListTools returns the result of tools/list.
func ListTools() map[string]any {
	list := make([]any, 0, len(tools))
	for _, t := range tools {
		list = append(list, map[string]any{
			"name":        t.name,
			"description": t.description,
			"inputSchema": inputSchema(t),
			"annotations": map[string]any{
				"readOnlyHint":    t.readOnly,
				"destructiveHint": false,
				"openWorldHint":   false,
			},
		})
	}
	return map[string]any{"tools": list}
}

// inputSchema is the JSON schema of a tool's arguments: path, run for a
// tool of one run, and the fields of its options under their json names.
func inputSchema(t tool) map[string]any {
	props := map[string]any{"path": map[string]any{"type": "string", "description": pathDoc}}
	if t.perRun {
		props["run"] = map[string]any{"type": "string", "description": leet.RunDoc}
	}
	options := reflect.TypeOf(t.options)
	for i := range options.NumField() {
		f := options.Field(i)
		name, _, _ := strings.Cut(f.Tag.Get("json"), ",")
		if !slices.Contains(followInputs, name) {
			props[name] = property(f)
		}
	}
	schema := map[string]any{"type": "object", "properties": props, "additionalProperties": false}
	if t.required != nil {
		schema["required"] = t.required
	}
	return schema
}

// property is the JSON schema of one field of an options struct.
func property(f reflect.StructField) map[string]any {
	p := map[string]any{"description": f.Tag.Get("doc")}
	switch f.Type {
	case reflect.TypeFor[string]():
		p["type"] = "string"
	case reflect.TypeFor[int](), reflect.TypeFor[int64](), reflect.TypeFor[*int64]():
		p["type"] = "integer"
	case reflect.TypeFor[bool]():
		p["type"] = "boolean"
	case reflect.TypeFor[[]string]():
		p["type"], p["items"] = "array", map[string]any{"type": "string"}
	case reflect.TypeFor[json.RawMessage]():
		p["type"] = "object"
	case reflect.TypeFor[controlMethod]():
		p["type"], p["enum"] = "string", leet.ControlMethods
	default:
		panic(fmt.Sprintf("leetmcp: no JSON schema for %s %s", f.Name, f.Type))
	}
	return p
}
