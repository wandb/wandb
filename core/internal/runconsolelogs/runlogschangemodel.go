package runconsolelogs

import (
	"encoding/json"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/wandb/wandb/core/internal/terminalemulator"
)

// Timestamps are generated in the Python ISO format (microseconds without Z)
const rfc3339Micro = "2006-01-02T15:04:05.000000Z07:00"

// RunLogsChangeModel tracks changes to a run's console logs.
type RunLogsChangeModel struct {
	// maxLines is the maximum number of lines to track before forgetting
	// about older lines.
	maxLines int

	// maxLineLength is the length at which to truncate lines.
	maxLineLength int

	// onChange is invoked whenever a line is modified.
	onChange func(int, *RunLogsLine)

	// getNow returns the current time.
	getNow func() time.Time

	firstLineNum int
	lines        []*RunLogsLine
}

// RunLogsLine is a mutable line in the W&B run's console logs.
type RunLogsLine struct {
	terminalemulator.LineContent

	// StreamPrefix is "ERROR " for stderr lines and "" for stdout lines.
	StreamPrefix string

	// Timestamp is the time this line was created.
	Timestamp time.Time

	// StreamLabel is the label for the stream prefix.
	StreamLabel string
}

// Clone returns a deep copy of the line.
func (l *RunLogsLine) Clone() *RunLogsLine {
	return &RunLogsLine{
		LineContent:  l.LineContent.Clone(),
		StreamPrefix: l.StreamPrefix,
		StreamLabel:  l.StreamLabel,
		Timestamp:    l.Timestamp,
	}
}

type logLine struct {
	Level   string `json:"level,omitempty"`
	TS      string `json:"ts"`
	Label   string `json:"label,omitempty"`
	Content string `json:"content"`
}

// MarshalJSON implements the json.Marshaler interface.
func (l *RunLogsLine) MarshalJSON() ([]byte, error) {
	// Format timestamp and trim the Z suffix as specified
	timestamp := strings.TrimSuffix(l.Timestamp.UTC().Format(rfc3339Micro), "Z")

	// Convert rune slice to string for content
	content := string(l.Content)

	// We only indicate the log level if it is an error
	level := ""
	if l.StreamPrefix != "" {
		level = "error"
	}

	// Create the JSON structure with the required fields
	jsonLine := logLine{
		Level:   level,
		TS:      timestamp,
		Label:   l.StreamLabel,
		Content: content,
	}

	// Marshal the custom struct to JSON
	return json.Marshal(jsonLine)
}

// StructuredFormat returns the line in the structured JSON format.
func (l *RunLogsLine) StructuredFormat() (string, error) {
	jsonLine, err := json.Marshal(l)
	if err != nil {
		return "", err
	}
	return string(jsonLine), nil
}

// LegacyFormat returns the line in the legacy plaintext format.
func (l *RunLogsLine) LegacyFormat() string {
	timestamp := strings.TrimSuffix(l.Timestamp.UTC().Format(rfc3339Micro), "Z")
	if l.StreamLabel != "" {
		return fmt.Sprintf(
			"%s%s [%s] %s",
			l.StreamPrefix,
			timestamp,
			l.StreamLabel,
			string(l.Content),
		)
	}
	return fmt.Sprintf(
		"%s%s %s",
		l.StreamPrefix,
		timestamp,
		string(l.Content),
	)
}

// LineSupplier returns a terminalemulator.LineSupplier for the stream prefix.
//
// The stream prefix should either be "" for stdout or "ERROR " for stderr.
// This is parsed by the W&B frontend, unfortunately.
//
// The stream label is used to prefix the stream prefix. It is used to add a
// namespace to the console output. Provided by the user.
func (o *RunLogsChangeModel) LineSupplier(streamPrefix, streamLabel string) *RunLogsLineSupplier {
	return &RunLogsLineSupplier{streamPrefix: streamPrefix, streamLabel: streamLabel, output: o}
}

// NextLine allocates a new line in the output buffer.
func (o *RunLogsChangeModel) NextLine(streamPrefix, streamLabel string) RunLogsLineRef {
	line := &RunLogsLine{}
	line.StreamPrefix = streamPrefix
	line.StreamLabel = streamLabel
	line.MaxLength = o.maxLineLength
	line.Timestamp = o.getNow()

	lineNum := o.firstLineNum + len(o.lines)
	o.lines = append(o.lines, line)

	if len(o.lines) > o.maxLines {
		o.firstLineNum += 1
		o.lines = slices.Delete(o.lines, 0, 1)
	}

	o.onChange(lineNum, line)

	return RunLogsLineRef{output: o, lineNum: lineNum}
}

// RunLogsLineSupplier allows a terminal emulator to request new lines in the
// output buffer.
type RunLogsLineSupplier struct {
	streamPrefix string
	streamLabel  string
	output       *RunLogsChangeModel
}

func (s *RunLogsLineSupplier) NextLine() terminalemulator.Line {
	return s.output.NextLine(s.streamPrefix, s.streamLabel)
}

// RunLogsLineRef is a reference to a console logs line.
//
// This is used by terminal emulators to map their view contents onto the
// output buffer.
type RunLogsLineRef struct {
	output  *RunLogsChangeModel
	lineNum int
}

func (l RunLogsLineRef) PutChar(c rune, offset int) {
	line := l.line()
	if line == nil {
		return
	}

	if line.PutChar(c, offset) {
		l.output.onChange(l.lineNum, line)
	}
}

func (l *RunLogsLineRef) line() *RunLogsLine {
	if l.lineNum < l.output.firstLineNum {
		return nil
	}

	idx := l.lineNum - l.output.firstLineNum
	if idx >= len(l.output.lines) {
		return nil
	}

	return l.output.lines[idx]
}
