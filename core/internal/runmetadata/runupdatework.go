package runmetadata

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
)

const (
	runUpsertDebounceSeconds = 5
)

type StreamRunMetadata interface {
	// SetRun is called when a new run is created successfully.
	//
	// It is called from the Sender goroutine and only if GetRun returns nil.
	SetRun(metadata *RunMetadata) error

	// Metadata returns the run set by a previous call to SetRun, or nil.
	//
	// It is called from the Sender goroutine.
	Metadata() (*RunMetadata, error)
}

// RunUpdateWork implements Work to initialize or update a run.
type RunUpdateWork struct {
	// Record contains the RunRecord that triggered this work.
	Record *spb.Record

	// StreamRunMetadata is used to update the stream's run information.
	StreamRunMetadata StreamRunMetadata

	// Respond is used to respond to the record, if necessary.
	//
	// It is called from the Sender goroutine.
	Respond func(*spb.Record, *spb.RunUpdateResult)

	Settings           *settings.Settings
	BeforeRunEndCtx    context.Context
	Operations         *wboperation.WandbOperations
	FeatureProvider    *featurechecker.ServerFeaturesCache
	GraphqlClientOrNil graphql.Client
	Logger             *observability.CoreLogger
}

// Accept implements Work.Accept.
func (w *RunUpdateWork) Accept(_ func(*spb.Record)) bool {
	return true
}

// Save implements Work.Save.
func (w *RunUpdateWork) Save(write func(*spb.Record)) {
	write(w.Record)
}

// Process implements Work.Process.
func (w *RunUpdateWork) Process(_ func(*spb.Record)) {
	if metadata, _ := w.StreamRunMetadata.Metadata(); metadata != nil {
		w.updateRun(metadata)
	} else {
		w.initRun()
	}
}

// updateRun updates an existing run.
func (w *RunUpdateWork) updateRun(run *RunMetadata) {
	run.Update(w.Record.GetRun())
}

// initRun creates a run for the first time.
func (w *RunUpdateWork) initRun() {
	metadata, err := InitRun(w.Record, RunMetadataParams{
		Settings: w.Settings,

		DebounceDelay: waiting.NewDelay(runUpsertDebounceSeconds * time.Second),

		BeforeRunEndCtx:    w.BeforeRunEndCtx,
		Operations:         w.Operations,
		FeatureProvider:    w.FeatureProvider,
		GraphqlClientOrNil: w.GraphqlClientOrNil,
		Logger:             w.Logger,
	})

	if err != nil {
		w.Logger.Error("runmetadata: failed to init run", "error", err)

		if w.Record.Control.GetMailboxSlot() != "" {
			w.Respond(w.Record, runInitErrorResult(err))
		}

		return
	}

	err = w.StreamRunMetadata.SetRun(metadata)
	if err != nil {
		w.Logger.CaptureError(
			fmt.Errorf(
				"runmetadata: failed to set run after initializing: %v",
				err))

		if w.Record.Control.GetMailboxSlot() != "" {
			w.Respond(w.Record, runInitErrorResult(err))
		}

		return
	}

	if w.Record.Control.GetMailboxSlot() != "" {
		updatedRun := proto.CloneOf(w.Record.GetRun())
		metadata.FillRunRecord(updatedRun)
		w.Respond(w.Record, &spb.RunUpdateResult{Run: updatedRun})
	}
}

// runInitErrorResult produces a RunUpdateResult for an initialization error.
//
// If the error is a runUpdateError, it is used to enhance the message.
// Otherwise, a generic error with an unknown code is returned.
func runInitErrorResult(err error) *spb.RunUpdateResult {
	var runUpdateError *RunUpdateError
	if errors.As(err, &runUpdateError) {
		return runUpdateError.AsResult()
	} else {
		return &spb.RunUpdateResult{
			Error: &spb.ErrorInfo{
				Message: fmt.Sprintf("Error initializing run: %v", err),
				Code:    spb.ErrorInfo_UNKNOWN,
			},
		}
	}
}

// BypassOfflineMode implements Work.BypassOfflineMode.
func (w *RunUpdateWork) BypassOfflineMode() bool {
	return true
}

// Sentinel implements Work.Sentinel.
func (w *RunUpdateWork) Sentinel() any {
	return nil
}

// DebugInfo implements Work.DebugInfo.
func (w *RunUpdateWork) DebugInfo() string {
	return fmt.Sprintf("RunUpdateWork; Control(%v)", w.Record.GetControl())
}
