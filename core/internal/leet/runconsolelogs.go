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

	// items mirrors lines in the KeyValuePair shape expected by ConsoleLogsPane.
	// It is updated incrementally so View does not need to reformat every line on
	// every render.
	items []KeyValuePair

	// maxLines caps the retained scrollback; the oldest lines are evicted past it.
	maxLines int

	// evicted counts lines dropped from the front; appendLine indices are absolute.
	evicted int

	// One filter per stream: an escape sequence may be split across raw records.
	stdoutFilter ansiFilter
	stderrFilter ansiFilter
}

// NewRunConsoleLogs creates an empty console log store with terminal
// emulators for stdout and stderr, keeping at most maxLines lines.
func NewRunConsoleLogs(maxLines int) *RunConsoleLogs {
	cl := &RunConsoleLogs{maxLines: maxLines}

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
		cl.stderrTerm.Write(cl.stderrFilter.strip(text))
	} else {
		cl.stdoutTerm.Write(cl.stdoutFilter.strip(text))
	}
}

// Items returns the assembled lines in [KeyValuePair] form.
//
// Callers must treat the returned slice as read-only.
func (cl *RunConsoleLogs) Items() []KeyValuePair {
	if len(cl.items) == len(cl.lines) {
		return cl.items
	}

	// Defensive rebuild for any future code path that
	// mutates lines without going through appendLine/onLineChanged.
	items := make([]KeyValuePair, len(cl.lines))
	for i, line := range cl.lines {
		items[i] = KeyValuePair{
			Key:   line.Timestamp.Format(consoleTimestampFormat),
			Value: line.Content,
		}
	}
	cl.items = items
	return cl.items
}

// appendLine is called by the line supplier when a new terminal line is
// created. Returns the absolute index for future PutChar callbacks.
func (cl *RunConsoleLogs) appendLine(isStderr bool) int {
	cl.lines = append(cl.lines, ConsoleLogLine{
		Timestamp: cl.currentTimestamp,
		IsStderr:  isStderr,
	})
	cl.items = append(cl.items, KeyValuePair{
		Key: cl.currentTimestamp.Format(consoleTimestampFormat),
	})

	if len(cl.lines) > cl.maxLines {
		n := len(cl.lines) - cl.maxLines
		cl.lines = cl.lines[n:]
		cl.items = cl.items[n:]
		cl.evicted += n
	}

	return cl.evicted + len(cl.lines) - 1
}

// onLineChanged is called when the terminal emulator modifies a
// character on an existing line via PutChar. idx is the absolute
// index returned by appendLine; evicted lines are silently dropped.
func (cl *RunConsoleLogs) onLineChanged(idx int, content []rune) {
	idx -= cl.evicted
	if idx < 0 || idx >= len(cl.lines) {
		return
	}
	value := strings.TrimRight(string(content), " \t")
	cl.lines[idx].Content = value
	if idx < len(cl.items) {
		cl.items[idx].Value = value
	}
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

// ---- ANSI filtering ----

// ansiFilterState tracks progress through an escape sequence across strip calls.
type ansiFilterState int

const (
	ansiGround ansiFilterState = iota
	ansiEsc                    // seen ESC
	ansiCSI                    // seen ESC [
	ansiOSC                    // seen ESC ]
	ansiOSCEsc                 // seen ESC inside an OSC string
)

// ansiFilter drops escape sequences the terminal emulator does not interpret
// (SGR colors, erase-line, OSC, ...); the cursor moves it does understand
// (ESC[A, ESC[B) pass through. A newline inside a sequence aborts it.
type ansiFilter struct {
	state ansiFilterState

	// csiParams is set once the current CSI sequence has parameter bytes.
	csiParams bool
}

func (f *ansiFilter) strip(s string) string {
	var b strings.Builder
	b.Grow(len(s))
	for _, r := range s {
		f.feed(r, &b)
	}
	return b.String()
}

// feed advances the filter by one rune, writing whatever should be kept.
func (f *ansiFilter) feed(r rune, b *strings.Builder) {
	switch f.state {
	case ansiGround:
		if r == '\x1b' {
			f.state = ansiEsc
		} else {
			b.WriteRune(r)
		}
	case ansiEsc:
		switch r {
		case '[':
			f.state = ansiCSI
			f.csiParams = false
		case ']':
			f.state = ansiOSC
		default:
			f.state = ansiGround
			if r == '\n' || r == '\r' {
				b.WriteRune(r)
			}
		}
	case ansiCSI:
		f.feedCSI(r, b)
	case ansiOSC:
		f.feedOSC(r, b)
	case ansiOSCEsc:
		if r == '\\' {
			f.state = ansiGround
		} else {
			f.state = ansiOSC
		}
	}
}

func (f *ansiFilter) feedCSI(r rune, b *strings.Builder) {
	switch {
	case r >= 0x40 && r <= 0x7e:
		if !f.csiParams && (r == 'A' || r == 'B') {
			b.WriteString("\x1b[")
			b.WriteRune(r)
		}
		f.state = ansiGround
	case r == '\x1b':
		f.state = ansiEsc
	case r == '\n' || r == '\r':
		b.WriteRune(r)
		f.state = ansiGround
	default:
		f.csiParams = true
	}
}

func (f *ansiFilter) feedOSC(r rune, b *strings.Builder) {
	switch r {
	case '\a':
		f.state = ansiGround
	case '\x1b':
		f.state = ansiOSCEsc
	case '\n', '\r':
		b.WriteRune(r)
		f.state = ansiGround
	}
}
