// Package runlogs uploads log lines a run's client writes directly.
//
// Unlike runconsolelogs, this pushes complete lines to the server.
package runlogs

import (
	"strings"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/runconsolelogs"
	"github.com/wandb/wandb/core/internal/sparselist"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// errorPrefix marks a line as an error.
const errorPrefix = "ERROR "

// Sender uploads a run's client-written log lines.
type Sender struct {
	mu           sync.Mutex
	isFinished   bool
	nextLineNum  int
	defaultLabel string
	getNow       func() time.Time
	fileStream   filestream.FileStream
	structured   func() bool
}

// Params contains parameters for creating a run logs Sender.
type Params struct {
	DefaultLabel string
	FileStream   filestream.FileStream

	// Structured reports whether to send lines in structured format.
	//
	// It is a function so the underlying server feature check is
	// evaluated lazily.
	Structured func() bool

	// GetNow is an optional function that returns the current time.
	GetNow func() time.Time
}

func New(params Params) *Sender {
	if params.GetNow == nil {
		params.GetNow = time.Now
	}

	if params.Structured == nil {
		// Default to the legacy format.
		params.Structured = func() bool { return false }
	}

	return &Sender{
		defaultLabel: params.DefaultLabel,
		getNow:       params.GetNow,
		fileStream:   params.FileStream,
		structured:   params.Structured,
	}
}

// Finish stops accepting lines.
func (s *Sender) Finish() {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.isFinished = true
}

// StreamLine appends a record's line to the run's logs.
func (s *Sender) StreamLine(record *spb.RunLogRequest) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.isFinished || s.fileStream == nil {
		return
	}

	label := s.defaultLabel
	if record.Label != "" {
		label = record.Label
	}

	prefix := ""
	if record.Level == spb.RunLogRequest_ERROR {
		prefix = errorPrefix
	}

	lines := sparselist.SparseList[string]{}

	// Lines in the log must not contain '\n'.
	for text := range strings.SplitSeq(strings.TrimSuffix(record.Line, "\n"), "\n") {
		lines.Put(s.nextLineNum, s.format(prefix, label, text))
		s.nextLineNum++
	}

	s.fileStream.StreamUpdate(&filestream.LogsUpdate{Lines: &lines})
}

// format renders one line the way the server parses it.
//
// The line type comes from runconsolelogs so that captured and written
// logs cannot drift apart on the wire; none of its terminal emulation
// is used here.
func (s *Sender) format(prefix, label, text string) string {
	line := &runconsolelogs.RunLogsLine{
		StreamPrefix: prefix,
		StreamLabel:  label,
		Timestamp:    s.getNow(),
	}
	line.Content = []rune(text)

	if s.structured() {
		if formatted, err := line.StructuredFormat(); err == nil {
			return formatted
		}
	}

	return line.LegacyFormat()
}
