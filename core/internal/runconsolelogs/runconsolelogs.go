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
	"github.com/wandb/wandb/core/internal/sparselist"
	"github.com/wandb/wandb/core/internal/terminalemulator"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"golang.org/x/time/rate"
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

	writer *debouncedWriter

	logger                *observability.CoreLogger
	runfilesUploaderOrNil runfiles.Uploader

	// captureEnabled indicates whether to capture console output.
	captureEnabled bool

	// fileWriter handles writing to disk (either single file or chunked).
	fileWriter *outputFileWriter

	// isMultipart indicates whether we're using chunked file output.
	isMultipart bool
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

	// Structured indicates whether to send the console output in structured format.
	Structured bool

	// Label is an optional prefix for the console output lines.
	Label string

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
		fsWriter = &filestreamWriter{
			FileStream: params.FileStreamOrNil,
			Structured: params.Structured,
		}
	}

	var fileWriter *outputFileWriter
	if params.EnableCapture {
		fileWriter = NewOutputFileWriter(OutputFileWriterParams{
			OutputFileName:   string(outputFileName),
			FilesDir:         params.FilesDir,
			Multipart:        params.Multipart,
			MaxChunkBytes:    int64(params.ChunkMaxBytes),
			MaxChunkDuration: time.Duration(int64(params.ChunkMaxSeconds)) * time.Second,
			Uploader:         params.RunfilesUploaderOrNil,
		})
	}

	writer := NewDebouncedWriter(
		rate.NewLimiter(rate.Every(10*time.Millisecond), 1),
		func(lines sparselist.SparseList[*RunLogsLine]) {
			if fileWriter != nil {
				if err := fileWriter.WriteToFile(lines); err != nil {
					params.Logger.CaptureError(
						fmt.Errorf(
							"runconsolelogs: failed to write to file: %v",
							err,
						))
				}
			}

			if fsWriter != nil {
				fsWriter.SendChanged(lines)
			}
		},
	)
	model := &RunLogsChangeModel{
		maxLines:      maxTerminalLines,
		maxLineLength: maxTerminalLineLength,
		onChange:      writer.OnChanged,
		getNow:        params.GetNow,
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

		writer:                writer,
		logger:                params.Logger,
		runfilesUploaderOrNil: params.RunfilesUploaderOrNil,
		captureEnabled:        params.EnableCapture,
		fileWriter:            fileWriter,
		isMultipart:           params.Multipart,
	}
}

// Finish sends any remaining logs.
//
// It must run before the filestream is closed.
func (s *Sender) Finish() {
	s.mu.Lock()
	s.isFinished = true
	s.mu.Unlock()

	s.writer.Finish()
	if s.captureEnabled && s.runfilesUploaderOrNil != nil {
		s.fileWriter.Finish()
	}
}

// StreamLogs saves captured console logs with the run.
func (s *Sender) StreamLogs(record *spb.OutputRawRecord) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if !s.captureEnabled || s.isFinished {
		return
	}

	switch record.OutputType {
	case spb.OutputRawRecord_STDOUT:
		s.stdoutTerm.Write(record.Line)

	case spb.OutputRawRecord_STDERR:
		s.stderrTerm.Write(record.Line)

	default:
		s.logger.CaptureError(
			errors.New("runconsolelogs: invalid OutputRawRecord type"),
			"type", record.OutputType,
		)
	}
}
