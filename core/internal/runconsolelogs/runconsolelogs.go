// Package runconsolelogs uploads a run's captured console output.
package runconsolelogs

import (
	"errors"
	"fmt"
	"path/filepath"
	"time"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sparselist"
	"github.com/wandb/wandb/core/internal/terminalemulator"
	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"golang.org/x/time/rate"
)

const (
	maxTerminalLines      = 32
	maxTerminalLineLength = 4096
)

// Sender processes OutputRawRecords.
type Sender struct {
	// stdoutTerm processes captured stdout text.
	stdoutTerm *terminalemulator.Terminal

	// stderrTerm processes captured stderr text.
	stderrTerm *terminalemulator.Terminal

	// consoleOutputFile is the run file path to which to write captured
	// console messages.
	consoleOutputFile paths.RelativePath

	writer *debouncedWriter

	logger    *observability.CoreLogger
	extraWork runwork.ExtraWork
}

type Params struct {
	ConsoleOutputFile paths.RelativePath

	Settings *settings.Settings
	Logger   *observability.CoreLogger

	ExtraWork runwork.ExtraWork

	// FileStreamOrNil is the filestream API.
	FileStreamOrNil filestream.FileStream

	// GetNow is an optional function that returns the current time.
	//
	// It is used for testing.
	GetNow func() time.Time
}

func New(params Params) *Sender {
	switch {
	case params.Settings == nil:
		panic("runconsolelogs: Settings is nil")
	case params.Logger == nil:
		panic("runconsolelogs: Logger is nil")
	case params.ExtraWork == nil:
		panic("runconsolelogs: ExtraWork is nil")
	}

	if params.GetNow == nil {
		params.GetNow = time.Now
	}

	var fsWriter *filestreamWriter
	if params.FileStreamOrNil != nil {
		fsWriter = &filestreamWriter{FileStream: params.FileStreamOrNil}
	}

	fileWriter, err := NewOutputFileWriter(
		filepath.Join(
			params.Settings.GetFilesDir(),
			string(params.ConsoleOutputFile),
		),
		params.Logger,
	)

	if err != nil {
		params.Logger.CaptureError(
			fmt.Errorf(
				"runconsolelogs: cannot write to file: %v",
				err,
			))
	}

	writer := NewDebouncedWriter(
		rate.NewLimiter(rate.Every(10*time.Millisecond), 1),
		params.ExtraWork.BeforeEndCtx(),
		func(lines sparselist.SparseList[*RunLogsLine]) {
			if fileWriter != nil {
				fileWriter.WriteToFile(lines)
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
			model.LineSupplier(""),
			maxTerminalLines,
		),
		stderrTerm: terminalemulator.NewTerminal(
			model.LineSupplier("ERROR "),
			maxTerminalLineLength,
		),

		consoleOutputFile: params.ConsoleOutputFile,

		writer:    writer,
		logger:    params.Logger,
		extraWork: params.ExtraWork,
	}
}

// Finish sends any remaining logs.
//
// It must run before the filestream is closed.
func (s *Sender) Finish() {
	s.writer.Wait()
	s.uploadOutputFile()
}

// StreamLogs saves captured console logs with the run.
func (s *Sender) StreamLogs(record *spb.OutputRawRecord) {
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

// uploadOutputFile uploads the console output file that we created.
func (s *Sender) uploadOutputFile() {
	s.extraWork.AddRecord(
		&spb.Record{
			RecordType: &spb.Record_Files{
				Files: &spb.FilesRecord{
					Files: []*spb.FilesItem{
						{
							Path: string(s.consoleOutputFile),
							Type: spb.FilesItem_WANDB,
						},
					},
				},
			},
		})
}
