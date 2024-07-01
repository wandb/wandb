package terminalemulator_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/terminalemulator"
)

type TestLineSupplier struct {
	Lines []*TestLine
}

func (p *TestLineSupplier) NextLine() terminalemulator.Line {
	line := &TestLine{
		LineContent: terminalemulator.LineContent{
			MaxLength: 64,
		},
	}

	p.Lines = append(p.Lines, line)

	return line
}

type TestLine struct {
	terminalemulator.LineContent
}

func (l *TestLine) PutChar(c rune, offset int) {
	_ = l.LineContent.PutChar(c, offset)
}

func TestCRLF(t *testing.T) {
	lines := &TestLineSupplier{}
	term := terminalemulator.NewTerminal(lines, 10)

	term.Write("one\ntwo\rwh")

	assert.Len(t, lines.Lines, 2)
	assert.Equal(t, "one", string(lines.Lines[0].Content))
	assert.Equal(t, "who", string(lines.Lines[1].Content))
}

func TestCursorMotion(t *testing.T) {
	lines := &TestLineSupplier{}
	term := terminalemulator.NewTerminal(lines, 10)

	term.Write("one\ntwo")
	term.Write("\x1b[Arous\x1b[Btasks")

	assert.Len(t, lines.Lines, 2)
	assert.Equal(t, "onerous", string(lines.Lines[0].Content))
	assert.Equal(t, "two    tasks", string(lines.Lines[1].Content))
}

func TestScrollPastHeight(t *testing.T) {
	lines := &TestLineSupplier{}
	term := terminalemulator.NewTerminal(lines, 2)
	term.Write("one\n")
	term.Write("two\n")
	term.Write("three\r\x1b[B") // \r\x1b[B is the same as \n
	term.Write("four\r")

	// At this point, the terminal has two lines in view:
	//   "three"
	//   "four"
	// The cursor is at the start of the second line. The cursor should be
	// unable to move up above "three".
	term.Write("\x1b[A\x1b[Amodified")

	assert.Len(t, lines.Lines, 4)
	assert.Equal(t, "one", string(lines.Lines[0].Content))
	assert.Equal(t, "two", string(lines.Lines[1].Content))
	assert.Equal(t, "modified", string(lines.Lines[2].Content))
	assert.Equal(t, "four", string(lines.Lines[3].Content))
}

func TestUnknownEscapeSequences(t *testing.T) {
	lines := &TestLineSupplier{}
	term := terminalemulator.NewTerminal(lines, 10)

	term.Write("\x1b?")
	term.Write("\x1b[?")

	assert.Equal(t, "\x1b?\x1b[?", string(lines.Lines[0].Content))
}
