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
	"github.com/wandb/wandb/core/internal/filetransfer"
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
type Sender struct {
	mu         sync.Mutex
	isFinished bool

	// stdoutTerm processes captured stdout text.
	stdoutTerm *terminalemulator.Terminal

	// stderrTerm processes captured stderr text.
	stderrTerm *terminalemulator.Terminal

	// consoleOutputFile is the path to the current file where we write captured
	// console messages.
	//
	// If multipart capture is enabled, it will get substituted every time a
	// new file is created.
	consoleOutputFile *paths.RelativePath

	writer *debouncedWriter

	logger                *observability.CoreLogger
	runfilesUploaderOrNil runfiles.Uploader

	// captureEnabled indicates whether to capture console output.
	captureEnabled bool
}

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

	// Size-based rollover threshold for multipart console logs, in bytes.
	ChunkBytes int32

	// Time-based rollover threshold for multipart console logs, in seconds.
	ChunkSeconds int32
}

func New(params Params) *Sender {
	if params.Logger == nil {
		panic("runconsolelogs: Logger is nil")
	}

	if params.GetNow == nil {
		params.GetNow = time.Now
	}

	var outputFileName *paths.RelativePath
	// Guaranteed not to fail.
	outputFileName, _ = paths.Relative(ConsoleFileName)

	// Insert label, if provided.
	if params.Label != "" {
		sanitizedLabel := fileutil.SanitizeFilename(params.Label)
		extension := filepath.Ext(string(*outputFileName))
		path, _ := paths.Relative(
			fmt.Sprintf(
				"%s_%s%s",
				strings.TrimSuffix(string(*outputFileName), extension),
				sanitizedLabel,
				extension,
			),
		)
		outputFileName = path
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
		var err error
		fileWriter, err = NewOutputFileWriter(
			outputFileWriterParams{
				filesDir:       params.FilesDir,
				outputFileName: outputFileName,
				logger:         params.Logger,
				multipart:      params.Multipart,
				chunkBytes:     params.ChunkBytes,
				chunkSeconds:   params.ChunkSeconds,
				onRotate: func(currentOutputFileName *paths.RelativePath) {
					fmt.Println(
						"+++ Uploading current file!",
						params.RunfilesUploaderOrNil,
						*currentOutputFileName,
					)
					// upload previous part immediately
					if params.EnableCapture && params.RunfilesUploaderOrNil != nil {
						params.RunfilesUploaderOrNil.UploadNow(
							*currentOutputFileName,
							filetransfer.RunFileKindWandb,
						)
					}
				},
			},
		)

		if err != nil {
			params.Logger.CaptureError(
				fmt.Errorf(
					"runconsolelogs: cannot write to file: %v",
					err,
				))
		}
	}

	writer := NewDebouncedWriter(
		rate.NewLimiter(rate.Every(10*time.Millisecond), 1),
		func(lines sparselist.SparseList[*RunLogsLine]) {
			if fileWriter != nil {
				err := fileWriter.WriteToFile(lines)

				if err != nil {
					params.Logger.CaptureError(
						fmt.Errorf(
							"runconsolelogs: failed to write to file: %v",
							err,
						))
					fileWriter = nil
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
			maxTerminalLineLength,
		),

		consoleOutputFile: fileWriter.currentOutputFileName,

		writer:                writer,
		logger:                params.Logger,
		runfilesUploaderOrNil: params.RunfilesUploaderOrNil,
		captureEnabled:        params.EnableCapture,
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
		fmt.Println("+++ Done, uploading\n", *s.consoleOutputFile)
		s.runfilesUploaderOrNil.UploadNow(
			*s.consoleOutputFile,
			filetransfer.RunFileKindWandb,
		)
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
