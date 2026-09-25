package runreader

import (
	"strings"
	"time"

	"github.com/wandb/wandb/core/internal/terminalemulator"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// consoleTermLines is the terminal emulator window size. Lines that
	// scroll out of the window are kept in the assembled output.
	consoleTermLines = 64

	// consoleLineLength is the maximum rune length of an assembled line.
	consoleLineLength = 4096
)

// ConsoleLine is one assembled line of a run's console output.
type ConsoleLine struct {
	Time    time.Time
	Stderr  bool
	Content string
}

// Console assembles raw console output and logger records into lines.
//
// Raw output carries ANSI escapes, carriage returns and partial lines, so
// each stream goes through a terminal emulator like the SDK's own console
// capture does. Emulation may rewrite earlier lines, for example progress
// bars redrawn with a carriage return.
type Console struct {
	stdout, stderr *terminalemulator.Terminal

	// current is the timestamp of the record being processed; new lines
	// inherit it.
	current time.Time

	lines []ConsoleLine

	// changed holds lines modified by the current record, including those
	// that have already scrolled out of the terminal's window.
	changed []*consoleLine
}

func NewConsole() *Console {
	c := &Console{}
	c.stdout = terminalemulator.NewTerminal(
		&consoleLineSupplier{console: c, stderr: false}, consoleTermLines)
	c.stderr = terminalemulator.NewTerminal(
		&consoleLineSupplier{console: c, stderr: true}, consoleTermLines)
	return c
}

// Process feeds one record through the emulator for its stream.
func (c *Console) Process(rec *spb.OutputRawRecord) {
	if ts := rec.GetTimestamp(); ts != nil {
		c.current = ts.AsTime()
	}
	if rec.GetOutputType() == spb.OutputRawRecord_STDERR {
		c.stderr.Write(rec.GetLine())
	} else {
		c.stdout.Write(rec.GetLine())
	}
	for _, line := range c.changed {
		c.lines[line.index].Content =
			strings.TrimRight(string(line.content.Content), " \t")
		line.changed = false
	}
	clear(c.changed)
	c.changed = c.changed[:0]
}

// ProcessLogger appends complete lines without affecting either terminal.
// Logger records carry no timestamp, so these lines have a zero Time.
func (c *Console) ProcessLogger(rec *spb.OutputLoggerRecord) {
	for line := range strings.SplitSeq(strings.TrimSuffix(rec.GetLine(), "\n"), "\n") {
		c.lines = append(c.lines, ConsoleLine{Content: line})
	}
}

// Lines returns the assembled lines in order. The slice is owned by the
// Console and changes with later Process calls.
func (c *Console) Lines() []ConsoleLine {
	return c.lines
}

type consoleLineSupplier struct {
	console *Console
	stderr  bool
}

func (s *consoleLineSupplier) NextLine() terminalemulator.Line {
	c := s.console
	c.lines = append(c.lines, ConsoleLine{Time: c.current, Stderr: s.stderr})
	return &consoleLine{
		content: terminalemulator.LineContent{MaxLength: consoleLineLength},
		console: c,
		index:   len(c.lines) - 1,
	}
}

type consoleLine struct {
	content terminalemulator.LineContent
	console *Console
	index   int
	changed bool
}

func (l *consoleLine) PutChar(c rune, offset int) {
	if l.content.PutChar(c, offset) && !l.changed {
		l.changed = true
		l.console.changed = append(l.console.changed, l)
	}
}
