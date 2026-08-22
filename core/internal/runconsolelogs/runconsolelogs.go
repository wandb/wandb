// Package runconsolelogs uploads a run's captured console output.
package runconsolelogs

import (
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/fileutil"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/terminalemulator"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	maxTerminalLines      = 32
	maxTerminalLineLength = 4096
	ConsoleFileName       = "output.log"
)

// Sender processes OutputRawRecords.
//
// It processes console output records, applies terminal emulation,
// and writes the results to file(s) and/or the filestream.
// In multipart mode, the output is split into chunks that are uploaded periodically.
type Sender struct {
	mu         sync.Mutex
	isFinished bool

	// stdoutTerm processes captured stdout text.
	stdoutTerm *terminalemulator.Terminal

	// stderrTerm processes captured stderr text.
	stderrTerm *terminalemulator.Terminal

	// consoleOutputFile is the run file path to which to write captured
	// console messages.
	consoleOutputFile paths.RelativePath

	logger                *observability.CoreLogger
	runfilesUploaderOrNil runfiles.Uploader

	// captureEnabled indicates whether to capture console output.
	//
	// TODO: Check captureEnabled in the client instead of here.
	captureEnabled bool

	// streamLabel is an optional label to add to all lines to disambiguate
	// logs from different machines in a mode="shared" run.
	streamLabel string

	// completeLinesOnly indicates whether to hold back a line's text
	// until its terminating newline arrives; see Params.
	completeLinesOnly bool

	// stdoutTail and stderrTail hold text after each stream's last
	// newline while completeLinesOnly is set.
	stdoutTail string
	stderrTail string

	// fsWriter pushes updates to the FileStream.
	fsWriter *filestreamWriter

	// fileWriter writes updates to disk (either single file or chunked).
	fileWriter *outputFileWriter

	// isMultipart indicates whether we're using chunked file output.
	isMultipart bool

	// model is the combined output of all logs sources.
	model *RunLogsChangeModel
}

// Params contains parameters for creating a console logs Sender.
type Params struct {
	// FilesDir is the directory in which to write the console output file.
	// Note this is actually the root directory for all run files.
	FilesDir string

	// EnableCapture indicates whether to capture console output.
	EnableCapture bool

	Logger *observability.CoreLogger

	RunfilesUploaderOrNil runfiles.Uploader

	// FileStreamOrNil is the filestream API.
	FileStreamOrNil filestream.FileStream

	// GetNow is an optional function that returns the current time.
	//
	// It is used for testing.
	GetNow func() time.Time

	// Structured reports whether to send console output in structured format.
	//
	// It is a function so the underlying server feature check is evaluated lazily.
	Structured func() bool

	// Label is an optional prefix for the console output lines.
	Label string

	// CompleteLinesOnly indicates whether to process captured console
	// output only as complete lines.
	//
	// Text after a line's last newline is held back until the rest of
	// the line arrives, so a backend that appends console updates
	// instead of overwriting them by offset never records a partial
	// line twice. Output that rewrites a line in place is flushed once
	// the held text grows past one terminal line.
	CompleteLinesOnly bool

	// Multipart indicates whether to capture multipart and potentially chunked logs.
	//
	// If True, the SDK writes console output to timestamped files
	// under the `logs/` directory instead of a single `output.log`.
	Multipart bool

	// ChunkMaxBytes is a size-based rollover threshold for multipart console logs, in bytes.
	ChunkMaxBytes int32

	// ChunkMaxSeconds is a time-based rollover threshold for multipart console logs, in seconds.
	ChunkMaxSeconds int32
}

func New(params Params) *Sender {
	if params.Logger == nil {
		panic("runconsolelogs: Logger is nil")
	}

	if params.GetNow == nil {
		params.GetNow = time.Now
	}

	// Guaranteed not to fail.
	p, _ := paths.Relative(ConsoleFileName)
	outputFileName := *p

	if params.Label != "" {
		sanitizedLabel := fileutil.SanitizeFilename(params.Label)
		extension := filepath.Ext(string(outputFileName))
		baseFileName := strings.TrimSuffix(string(outputFileName), extension)
		p, _ := paths.Relative(
			fmt.Sprintf("%s_%s%s", baseFileName, sanitizedLabel, extension),
		)
		outputFileName = *p
	}

	var fsWriter *filestreamWriter
	if params.FileStreamOrNil != nil {
		fsWriter = NewFileStreamWriter(
			params.Structured,
			params.FileStreamOrNil,
		)
	}

	var fileWriter *outputFileWriter
	if params.EnableCapture {
		fileWriter = NewOutputFileWriter(OutputFileWriterParams{
			OutputFileName:   string(outputFileName),
			FilesDir:         params.FilesDir,
			Multipart:        params.Multipart,
			MaxChunkBytes:    int64(params.ChunkMaxBytes),
			MaxChunkDuration: time.Duration(int64(params.ChunkMaxSeconds)) * time.Second,
			Logger:           params.Logger,
			UploaderOrNil:    params.RunfilesUploaderOrNil,
		})
	}

	model := &RunLogsChangeModel{
		maxLines:      maxTerminalLines,
		maxLineLength: maxTerminalLineLength,
		getNow:        params.GetNow,
		onChange: func(lineNum int, line *RunLogsLine) {
			if fileWriter != nil {
				fileWriter.UpdateLine(lineNum, line)
			}
			if fsWriter != nil {
				fsWriter.UpdateLine(lineNum, line)
			}
		},
	}

	return &Sender{
		stdoutTerm: terminalemulator.NewTerminal(
			model.LineSupplier("", params.Label),
			maxTerminalLines,
		),
		stderrTerm: terminalemulator.NewTerminal(
			model.LineSupplier("ERROR ", params.Label),
			maxTerminalLines,
		),

		consoleOutputFile: outputFileName,

		logger:                params.Logger,
		runfilesUploaderOrNil: params.RunfilesUploaderOrNil,
		captureEnabled:        params.EnableCapture,
		streamLabel:           params.Label,
		completeLinesOnly:     params.CompleteLinesOnly,
		fsWriter:              fsWriter,
		fileWriter:            fileWriter,
		isMultipart:           params.Multipart,
		model:                 model,
	}
}

// Finish sends any remaining logs.
//
// It must run before the filestream is closed.
func (s *Sender) Finish() {
	s.mu.Lock()
	// Lines still waiting for a newline would otherwise be lost.
	if s.stdoutTail != "" {
		s.stdoutTerm.Write(s.stdoutTail)
		s.stdoutTail = ""
	}
	if s.stderrTail != "" {
		s.stderrTerm.Write(s.stderrTail)
		s.stderrTail = ""
	}
	s.isFinished = true
	s.mu.Unlock()

	if s.fsWriter != nil {
		s.fsWriter.Finish()
	}
	if s.fileWriter != nil {
		s.fileWriter.Finish()
	}
}

// StreamLoggerOutput appends a custom line of text to the run's console logs.
//
// This implements `run.write_logs()` in the Python client.
func (s *Sender) StreamLoggerOutput(record *spb.OutputLoggerRecord) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.isFinished {
		return
	}

	label := s.streamLabel
	if record.Label != "" {
		label = record.Label
	}

	// Lines in the model must not contain '\n'.
	for line := range strings.SplitSeq(strings.TrimSuffix(record.Line, "\n"), "\n") {
		// We can discard the line reference because we never change the line.
		_ = s.model.NextLine("", label, line)
	}
}

// StreamLogs updates the run's captured console logs.
func (s *Sender) StreamLogs(record *spb.OutputRawRecord) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if !s.captureEnabled || s.isFinished {
		return
	}

	switch record.OutputType {
	case spb.OutputRawRecord_STDOUT:
		s.writeToTerm(s.stdoutTerm, &s.stdoutTail, record.Line)

	case spb.OutputRawRecord_STDERR:
		s.writeToTerm(s.stderrTerm, &s.stderrTail, record.Line)

	default:
		s.logger.CaptureError(
			"runconsolelogs",
			errors.New("runconsolelogs: invalid OutputRawRecord type"),
			"type",
			record.OutputType,
		)
	}
}

// writeToTerm forwards captured console text to a terminal.
//
// With completeLinesOnly set, text after the input's last newline waits
// in tail for the rest of its line, so a line is never processed in two
// pieces; see Params.CompleteLinesOnly. A tail past one terminal line
// flushes anyway, bounding the buffer when output rewrites a line in
// place instead of ending it.
//
// Callers must hold s.mu.
func (s *Sender) writeToTerm(
	term *terminalemulator.Terminal,
	tail *string,
	input string,
) {
	if !s.completeLinesOnly {
		term.Write(input)
		return
	}

	buffered := *tail + input
	complete := ""
	if cut := strings.LastIndexByte(buffered, '\n'); cut >= 0 {
		complete, buffered = buffered[:cut+1], buffered[cut+1:]
	}
	if len(buffered) >= maxTerminalLineLength {
		complete, buffered = complete+buffered, ""
	}

	if complete != "" {
		term.Write(complete)
	}
	*tail = buffered
}
