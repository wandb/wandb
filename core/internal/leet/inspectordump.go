package leet

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"github.com/wandb/simplejsonext"
	"google.golang.org/protobuf/encoding/protojson"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// followPollInterval is how often DumpRecords checks a live run's file for
// new records while following it.
const followPollInterval = time.Second

// DumpOptions configures DumpRecords.
type DumpOptions struct {
	// JSON prints one JSON object per record per line instead of prototext.
	JSON bool

	// Follow keeps printing records as the run writes them, until it exits
	// or its file goes unchanged for IdleTimeout.
	Follow bool

	// IdleTimeout is how long Follow waits for a write before giving up.
	// Zero waits forever.
	IdleTimeout time.Duration
}

// DumpRecords writes the records in a .wandb file to stdout. An empty
// runFile resolves to the latest run in wandbDir, like starting LEET in
// single-run mode.
//
// Records are prototext stanzas, each preceded by a "# record N: <type>"
// line, or JSON lines with opts.JSON. Notes about skipped corrupt regions
// and an incomplete tail are "#" comment lines in prototext output, so it
// remains a sequence of valid stanzas, and go to stderr with opts.JSON.
func DumpRecords(
	runFile, wandbDir string,
	stdout, stderr io.Writer,
	opts DumpOptions,
) error {
	path, err := resolveWandbFile(runFile, wandbDir)
	if err != nil {
		return err
	}

	reader, err := transactionlog.OpenReader(path, observability.NewNoOpLogger())
	if err != nil {
		return err
	}
	defer reader.Close()

	note := func(text string) error {
		if opts.JSON {
			_, err := fmt.Fprintln(stderr, "wandb leet inspect:", text)
			return err
		}
		_, err := fmt.Fprintln(stdout, "#", text)
		return err
	}

	sessionFeatures.mark(dumpFeature(opts))
	if !opts.JSON {
		_, err := fmt.Fprintln(stderr, "wandb leet inspect: --summary prints"+
			" the run's state, latest metrics and console tail; --json prints"+
			" one record per line; --follow keeps printing new records.")
		if err != nil {
			return err
		}
	}

	exited := false
	for num := 1; ; {
		record, err := readRecord(reader)

		switch {
		case errors.Is(err, io.EOF), errors.Is(err, io.ErrUnexpectedEOF):
			if !opts.Follow || exited {
				if errors.Is(err, io.ErrUnexpectedEOF) {
					return note("reached the end of an incomplete .wandb file" +
						" (the run may still be active or was interrupted)")
				}
				return nil
			}

			info, err := os.Stat(path)
			if err != nil {
				return err
			}
			idle := time.Since(info.ModTime())
			if opts.IdleTimeout > 0 && idle > opts.IdleTimeout {
				return note(fmt.Sprintf(
					"no writes for %v; the run may have crashed",
					idle.Round(time.Second)))
			}
			if err := reader.ResetLastRead(); err != nil {
				return err
			}
			time.Sleep(followPollInterval)
			continue

		case errors.Is(err, errCorruptSkipped):
			if err := note(err.Error()); err != nil {
				return err
			}
			continue

		case err != nil:
			return err
		}

		if record.GetExit() != nil {
			exited = true
		}

		if opts.JSON {
			err = writeRecordJSON(stdout, num, record)
		} else {
			_, err = fmt.Fprintf(stdout, "# record %d: %s\n%s\n",
				num, recordTypeName(record), inspectorMarshal.Format(record))
		}
		if err != nil {
			return err
		}
		num++
	}
}

// errCorruptSkipped wraps a read error after which reading continues past
// the corrupt data.
var errCorruptSkipped = errors.New("skipped corrupt data")

// readRecord reads the next record.
//
// An error wrapping errCorruptSkipped means corrupt data was skipped and
// reading can go on. Any other error besides EOF would repeat on every
// call, as for a file that is not a transaction log.
func readRecord(reader *transactionlog.Reader) (*spb.Record, error) {
	before := reader.NextRecordOffset()
	record, err := reader.Read()
	if err != nil &&
		!errors.Is(err, io.EOF) &&
		!errors.Is(err, io.ErrUnexpectedEOF) &&
		reader.NextRecordOffset() > before {
		return nil, fmt.Errorf("%w: %v", errCorruptSkipped, err)
	}
	return record, err
}

var protojsonOptions = protojson.MarshalOptions{UseProtoNames: true}

func dumpFeature(opts DumpOptions) string {
	switch {
	case opts.Follow:
		return "inspector.follow"
	case opts.JSON:
		return "inspector.print_json"
	default:
		return "inspector.print"
	}
}

// writeRecordJSON writes a record as one line of JSON:
//
//	{"num":2,"type":"history","history":{"item":{"loss":0.5},...}}
//
// The payload is the record's protojson with proto field names. Lists of
// logged items, such as history items or summary and config updates,
// become objects mapping each dotted key to its decoded value; NaN and
// infinite values become the strings "NaN", "Infinity" and "-Infinity".
// A history step is a number, and an exit record's code and a console
// line's stream are present even when zero, unlike in protojson.
func writeRecordJSON(w io.Writer, num int, record *spb.Record) error {
	msg := record.ProtoReflect()
	field := msg.WhichOneof(msg.Descriptor().Oneofs().ByName("record_type"))
	if field == nil {
		_, err := fmt.Fprintf(w, "{\"num\":%d,\"type\":\"unknown\"}\n", num)
		return err
	}

	payloadJSON, err := protojsonOptions.Marshal(msg.Get(field).Message().Interface())
	if err != nil {
		return err
	}
	var payload map[string]any
	if err := json.Unmarshal(payloadJSON, &payload); err != nil {
		return err
	}
	delete(payload, "_info")
	switch rec := record.RecordType.(type) {
	case *spb.Record_History:
		if step := rec.History.GetStep(); step != nil {
			payload["step"] = map[string]any{"num": step.GetNum()}
		}
	case *spb.Record_Exit:
		payload["exit_code"] = rec.Exit.GetExitCode()
	case *spb.Record_OutputRaw:
		payload["output_type"] = rec.OutputRaw.GetOutputType().String()
	}

	var line bytes.Buffer
	fmt.Fprintf(&line, "{\"num\":%d,\"type\":%q,%q:", num, recordTypeName(record), field.Name())
	if err := encodeJSON(&line, decodeLoggedItems(payload), ""); err != nil {
		return err
	}
	line.Truncate(line.Len() - 1)
	line.WriteString("}\n")
	_, err = w.Write(line.Bytes())
	return err
}

// encodeJSON writes v and a newline as JSON without escaping HTML
// characters, so that the output can be searched for text like "a->b".
func encodeJSON(w io.Writer, v any, indent string) error {
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", indent)
	return enc.Encode(jsonValue(v))
}

// jsonValue prepares a decoded value for encoding/json: NaN and infinities
// become strings, and empty objects and lists, which simplejsonext decodes
// as nil, stay {} and [] rather than becoming null.
func jsonValue(v any) any {
	switch v := v.(type) {
	case map[string]any:
		if v == nil {
			return map[string]any{}
		}
		for k, e := range v {
			v[k] = jsonValue(e)
		}
		return v
	case []any:
		if v == nil {
			return []any{}
		}
		for i, e := range v {
			v[i] = jsonValue(e)
		}
		return v
	default:
		return simplejsonext.WalkDeNaN(v)
	}
}

// decodeLoggedItems replaces lists of {key|nested_key, value_json} objects
// in a decoded protojson value with objects mapping keys to decoded values.
func decodeLoggedItems(v any) any {
	switch v := v.(type) {
	case map[string]any:
		for k, e := range v {
			v[k] = decodeLoggedItems(e)
		}
	case []any:
		if items, ok := loggedItems(v); ok {
			return items
		}
		for i, e := range v {
			v[i] = decodeLoggedItems(e)
		}
	}
	return v
}

// loggedItems converts a list of logged items to an object, or returns
// false if the list is not one.
func loggedItems(list []any) (map[string]any, bool) {
	if len(list) == 0 {
		return nil, false
	}

	items := make(map[string]any, len(list))
	for _, e := range list {
		item, ok := e.(map[string]any)
		if !ok {
			return nil, false
		}
		valueJSON, ok := item["value_json"].(string)
		if !ok {
			return nil, false
		}

		key, _ := item["key"].(string)
		if nested, ok := item["nested_key"].([]any); ok && len(nested) > 0 {
			parts := make([]string, len(nested))
			for i, p := range nested {
				parts[i] = fmt.Sprint(p)
			}
			key = strings.Join(parts, ".")
		}

		if value, err := simplejsonext.UnmarshalString(valueJSON); err == nil {
			items[key] = value
		} else {
			items[key] = valueJSON
		}
	}
	return items, true
}
