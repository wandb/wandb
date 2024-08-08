package runconsolelogs

import (
	"slices"
	"time"

	"github.com/wandb/wandb/core/internal/terminalemulator"
)

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
}

// Clone returns a deep copy of the line.
func (l *RunLogsLine) Clone() *RunLogsLine {
	return &RunLogsLine{
		LineContent:  l.LineContent.Clone(),
		StreamPrefix: l.StreamPrefix,
		Timestamp:    l.Timestamp,
	}
}

// LineSupplier returns a terminalemulator.LineSupplier for the stream prefix.
//
// The stream prefix should either be "" for stdout or "ERROR " for stderr.
// This is parsed by the W&B frontend, unfortunately.
func (o *RunLogsChangeModel) LineSupplier(streamPrefix string) *RunLogsLineSupplier {
	return &RunLogsLineSupplier{streamPrefix: streamPrefix, output: o}
}

// NextLine allocates a new line in the output buffer.
func (o *RunLogsChangeModel) NextLine(streamPrefix string) RunLogsLineRef {
	line := &RunLogsLine{}
	line.StreamPrefix = streamPrefix
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
	output       *RunLogsChangeModel
}

func (s *RunLogsLineSupplier) NextLine() terminalemulator.Line {
	return s.output.NextLine(s.streamPrefix)
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
