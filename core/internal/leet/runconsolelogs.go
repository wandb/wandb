package leet

import (
	"strings"
	"time"

	"github.com/wandb/wandb/core/internal/terminalemulator"
)

// Console log assembly constants.
const (
	// maxConsoleTermLines is the terminal emulator window size.
	//
	// This bounds memory for cursor-addressable output. Lines that scroll
	// out of the terminal window are preserved in the assembled slice.
	maxConsoleTermLines = 64

	// maxConsoleLineLength is the maximum rune length per assembled line.
	maxConsoleLineLength = 4096

	// consoleTimestampFormat is the display format for timestamps.
	//
	// Adapted from the structured format used by the filestreamWriter
	// (rfc3339Micro), but shortened for compact TUI display.
	consoleTimestampFormat = "15:04:05"
)

// ConsoleLogLine is an assembled, display-ready line of console output.
type ConsoleLogLine struct {
	Timestamp time.Time
	Content   string
	IsStderr  bool
}

// RunConsoleLogs assembles raw output_raw records into display-ready lines.
//
// Raw terminal output may contain ANSI escape codes, partial lines, and
// carriage returns. This mirrors the approach used by the
// runconsolelogs.Sender in the core library: each stream (stdout/stderr)
// gets its own [terminalemulator.Terminal] that correctly handles cursor
// movements, overwrites, and newline assembly.
//
// Like [RunOverview], this is a data-model component; the [ConsoleLogsPane]
// handles presentation.
type RunConsoleLogs struct {
	stdoutTerm *terminalemulator.Terminal
	stderrTerm *terminalemulator.Terminal

	// currentTimestamp is set before each Write call so that newly
	// created lines inherit the record's proto timestamp.
	currentTimestamp time.Time

	// lines is the assembled, ordered log output. Lines from both
	// streams are interleaved in arrival order.
	lines []ConsoleLogLine
}

// NewRunConsoleLogs creates an empty console log store with terminal
// emulators for stdout and stderr.
func NewRunConsoleLogs() *RunConsoleLogs {
	cl := &RunConsoleLogs{}

	cl.stdoutTerm = terminalemulator.NewTerminal(
		&consoleLineSupplier{owner: cl, isStderr: false},
		maxConsoleTermLines,
	)
	cl.stderrTerm = terminalemulator.NewTerminal(
		&consoleLineSupplier{owner: cl, isStderr: true},
		maxConsoleTermLines,
	)

	return cl
}

// ProcessRaw feeds a raw output record through the terminal emulator.
//
// The text may contain newlines, ANSI escape codes (e.g. cursor-up),
// and partial lines. The emulator handles all of this and calls back
// into the line supplier to create assembled lines — eliminating the
// extra-newline problem that occurs with naive line splitting.
func (cl *RunConsoleLogs) ProcessRaw(text string, isStderr bool, ts time.Time) {
	cl.currentTimestamp = ts

	if isStderr {
		cl.stderrTerm.Write(text)
	} else {
		cl.stdoutTerm.Write(text)
	}
}

// Items converts the assembled lines into [KeyValuePair] items suitable
// for display in a [PagedList]. Keys are compact timestamps (HH:MM:SS),
// values are the line content.
func (cl *RunConsoleLogs) Items() []KeyValuePair {
	items := make([]KeyValuePair, len(cl.lines))
	for i, line := range cl.lines {
		items[i] = KeyValuePair{
			Key:   line.Timestamp.Format(consoleTimestampFormat),
			Value: line.Content,
		}
	}
	return items
}

// appendLine is called by the line supplier when a new terminal line is
// created. Returns the index for future PutChar callbacks.
func (cl *RunConsoleLogs) appendLine(isStderr bool) int {
	idx := len(cl.lines)
	cl.lines = append(cl.lines, ConsoleLogLine{
		Timestamp: cl.currentTimestamp,
		IsStderr:  isStderr,
	})
	return idx
}

// onLineChanged is called when the terminal emulator modifies a
// character on an existing line via PutChar.
func (cl *RunConsoleLogs) onLineChanged(idx int, content []rune) {
	if idx < 0 || idx >= len(cl.lines) {
		return
	}
	cl.lines[idx].Content = strings.TrimRight(string(content), " \t")
}

// ---- Terminal emulator integration ----

// consoleLineSupplier implements [terminalemulator.LineSupplier].
type consoleLineSupplier struct {
	owner    *RunConsoleLogs
	isStderr bool
}

func (s *consoleLineSupplier) NextLine() terminalemulator.Line {
	idx := s.owner.appendLine(s.isStderr)
	return &consoleLine{
		content:  terminalemulator.LineContent{MaxLength: maxConsoleLineLength},
		owner:    s.owner,
		index:    idx,
		isStderr: s.isStderr,
	}
}

// consoleLine implements [terminalemulator.Line] for a single assembled line.
type consoleLine struct {
	content  terminalemulator.LineContent
	owner    *RunConsoleLogs
	index    int
	isStderr bool
}

func (l *consoleLine) PutChar(c rune, offset int) {
	if l.content.PutChar(c, offset) {
		l.owner.onLineChanged(l.index, l.content.Content)
	}
}
