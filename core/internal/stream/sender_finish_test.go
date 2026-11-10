package stream_test

import (
	"errors"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/filestreamtest"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/runworktest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// slowFinishFileStream is a FileStream whose final upload blocks until
// released and then fails.
type slowFinishFileStream struct {
	*filestreamtest.FakeFileStream

	release  chan struct{}
	finished chan struct{}
	err      error
}

func (fs *slowFinishFileStream) FinishWithExit(int32) { fs.FinishWithoutExit() }

func (fs *slowFinishFileStream) FinishWithoutExit() {
	<-fs.release
	fs.err = errors.New("final upload rejected")
	close(fs.finished)
}

func (fs *slowFinishFileStream) Err() error {
	select {
	case <-fs.finished:
		return fs.err
	default:
		return nil
	}
}

func TestSenderDo_WaitsForFinalUploadBeforeReturning(t *testing.T) {
	fileStream := &slowFinishFileStream{
		FakeFileStream: filestreamtest.NewFakeFileStream(),
		release:        make(chan struct{}),
		finished:       make(chan struct{}),
	}
	x := makeSenderWithFileStream(t, gqlmock.NewMockClient(), fileStream)

	work := make(chan runwork.Work, 1)
	request, _ := runworktest.SimpleRequest(t, "exit")
	work <- runwork.Work{
		WorkImpl: runwork.WorkFromRecord(&spb.Record{
			RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{}},
		}),
		Request: request,
	}
	// Close the work channel right after the exit record, without waiting
	// for the exit response.
	close(work)

	done := make(chan struct{})
	go func() {
		defer close(done)
		x.Sender.Do(work)
	}()

	select {
	case <-done:
		t.Fatal("Do returned before the final upload finished")
	case <-time.After(200 * time.Millisecond):
	}

	close(fileStream.release)
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Do did not return after the final upload finished")
	}
	require.EqualError(t, x.Sender.FileStreamError(), "final upload rejected")
}
