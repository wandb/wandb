package runsync

import (
	"errors"
	"fmt"
	"io"
	"os"
	"sync"

	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var runReaderProviders = wire.NewSet(
	wire.Struct(new(RunReaderFactory), "*"),
)

// RunReaderFactory constructs RunReader.
type RunReaderFactory struct {
	Logger *observability.CoreLogger
}

// RunReader gets information out of .wandb files.
type RunReader struct {
	path string // transaction log path

	seenExit bool // whether we've processed an exit record yet

	logger       *observability.CoreLogger
	recordParser stream.RecordParser
	runWork      runwork.RunWork
}

func (f *RunReaderFactory) New(
	path string,
	recordParser stream.RecordParser,
	runWork runwork.RunWork,
) *RunReader {
	return &RunReader{
		path: path,

		logger:       f.Logger,
		recordParser: recordParser,
		runWork:      runWork,
	}
}

// ExtractRunInfo quickly reads and returns basic run information.
func (r *RunReader) ExtractRunInfo() (*RunInfo, error) {
	r.logger.Info("runsync: getting info", "path", r.path)

	store, err := r.open()
	if err != nil {
		return nil, err
	}
	defer store.Close()

	for {
		record, err := store.Read()
		if err != nil {
			return nil, fmt.Errorf("runsync: didn't find run info: %v", err)
		}

		if run := record.GetRun(); run != nil {
			return &RunInfo{RunID: run.RunId}, nil
		}
	}
}

// ProcessTransactionLog processes the .wandb file and adds to RunWork.
//
// Returns an error if it fails to start or on partial success.
//
// Closes RunWork at the end, even on error. If there was no Exit record,
// creates one with an exit code of 1.
func (r *RunReader) ProcessTransactionLog() error {
	r.logger.Info("runsync: starting to read", "path", r.path)

	defer r.closeRunWork()

	reader, err := r.open()
	if err != nil {
		return err
	}
	defer reader.Close()

	for {
		record, err := reader.Read()
		if errors.Is(err, io.EOF) {
			r.logger.Info("runsync: done reading", "path", r.path)
			return nil
		}

		if err != nil {
			// TODO: Keep going to skip corrupt data.
			//   Need to update Read so that we can tell if we can recover.
			return err
		}

		r.parseAndAddWork(record)

		switch {
		case record.GetExit() != nil:
			r.seenExit = true
		case record.GetRun() != nil:
			// The RunStart request is required to come after a Run record,
			// but its contents are irrelevant when syncing. It causes
			// the Sender to start FileStream.
			r.parseAndAddWork(
				&spb.Record{RecordType: &spb.Record_Request{
					Request: &spb.Request{RequestType: &spb.Request_RunStart{
						RunStart: &spb.RunStartRequest{},
					}},
				}})
		}
	}
}

// closeRunWork closes RunWork creating an exit record if one hasn't been seen.
func (r *RunReader) closeRunWork() {
	if !r.seenExit {
		r.logger.Warn(
			"runsync: no exit record in file, using exit code 1 (failed)",
			"path", r.path)

		exitRecord := &spb.Record{
			RecordType: &spb.Record_Exit{
				Exit: &spb.RunExitRecord{
					ExitCode: 1,
				},
			},
		}

		r.runWork.AddWork(r.recordParser.Parse(exitRecord))
	}

	r.runWork.Close()
}

// open returns an opened transaction log Reader.
func (r *RunReader) open() (*transactionlog.Reader, error) {
	reader, err := transactionlog.OpenReader(r.path, r.logger)

	if err == nil {
		return reader, nil
	}

	syncErr := &SyncError{
		Err:     err,
		Message: "failed to open store",
	}

	switch {
	case errors.Is(err, os.ErrNotExist):
		syncErr.UserText = fmt.Sprintf("File does not exist: %s", r.path)

	case errors.Is(err, os.ErrPermission):
		syncErr.UserText = fmt.Sprintf(
			"Permission error opening file for reading: %s",
			r.path,
		)
	}

	return nil, syncErr
}

// parseAndAddWork parses the record and pushes it to RunWork.
func (r *RunReader) parseAndAddWork(record *spb.Record) {
	work := r.recordParser.Parse(record)

	wg := &sync.WaitGroup{}
	work.Schedule(wg, func() { r.runWork.AddWork(work) })

	// We always process records in reading order.
	wg.Wait()
}
