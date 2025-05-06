// Package runmetadata manages run data that's uploaded via UpsertBucket.
package runmetadata

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runbranch"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RunMetadata manages and syncs info about a run that's usually set on init and
// rarely changed.
//
// The RunMetadata object makes "UpsertBucket" requests when values change,
// debouncing them to avoid rapid-fire network requests.
type RunMetadata struct {
	mu sync.Mutex
	wg sync.WaitGroup

	debounceDelay waiting.Delay

	settings           *settings.Settings
	beforeRunEndCtx    context.Context
	operations         *wboperation.WandbOperations
	graphqlClientOrNil graphql.Client
	logger             *observability.CoreLogger

	// done is closed when Finish is called.
	done chan struct{}
}

type RunMetadataParams struct {
	DebounceDelay waiting.Delay

	Settings           *settings.Settings
	BeforeRunEndCtx    context.Context
	Operations         *wboperation.WandbOperations
	FeatureProvider    *featurechecker.ServerFeaturesCache
	GraphqlClientOrNil graphql.Client
	Logger             *observability.CoreLogger
}

func (params *RunMetadataParams) panicIfNotFilled() {
	switch {
	case params.DebounceDelay == nil:
		panic("runmetadata: DebounceDelay is nil")
	case params.Settings == nil:
		panic("runmetadata: Settings is nil")
	case params.BeforeRunEndCtx == nil:
		panic("runmetadata: BeforeRunEndCtx is nil")
	case params.FeatureProvider == nil:
		panic("runmetadata: FeatureProvider is nil")
	case params.Logger == nil:
		panic("runmetadata: Logger is nil")
	}
}

// InitRun upserts a new run and returns it.
//
// This function blocks until the run is created.
//
// The returned error may wrap a runUpdateError.
func InitRun(
	record *spb.Record,
	params RunMetadataParams,
) (*RunMetadata, error) {
	params.panicIfNotFilled()

	metadata := &RunMetadata{
		debounceDelay: params.DebounceDelay,

		settings:           params.Settings,
		beforeRunEndCtx:    params.BeforeRunEndCtx,
		operations:         params.Operations,
		graphqlClientOrNil: params.GraphqlClientOrNil,
		logger:             params.Logger,

		done: make(chan struct{}),
	}

	operation := metadata.operations.New("creating run")
	defer operation.Finish()
	ctx := operation.Context(metadata.beforeRunEndCtx)

	// TODO: Update metadata if resuming, rewinding or forking.

	// If we're offline, skip upserting.
	if metadata.graphqlClientOrNil == nil {
		return metadata, nil
	}

	metadata.mu.Lock()
	defer metadata.mu.Unlock()

	// Upsert the run.
	response, err := metadata.lockedDoUpsert(ctx)

	if err != nil {
		return nil, &runUpdateError{
			UserMessage: fmt.Sprintf("Error uploading run: %v", err),
			Cause:       err,
			Code:        spb.ErrorInfo_COMMUNICATION,
		}
	}

	// Fill some metadata based on the server response.
	metadata.lockedUpdateFromUpsert(response)

	// Begin processing updates.
	metadata.wg.Add(1)
	go func() {
		defer metadata.wg.Done()
		metadata.syncPeriodically()
	}()

	return metadata, nil
}

// Update schedules an update to some part of the run metadata.
func (metadata *RunMetadata) Update(runRecord *spb.RunRecord) {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	panic("TODO: Unimplemented.")
}

// UpdateConfig schedules an update to the run's config.
func (metadata *RunMetadata) UpdateConfig(config *spb.ConfigRecord) {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	panic("TODO: Unimplemented.")
}

// UpdateTelemetry schedules an update to the run's telemetry.
func (metadata *RunMetadata) UpdateTelemetry(telemetry *spb.TelemetryRecord) {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	panic("TODO: Unimplemented.")
}

// UpdateMetrics schedules an update to the run's metrics in the config.
func (metadata *RunMetadata) UpdateMetrics(metric *spb.MetricRecord) {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	panic("TODO: Unimplemented.")
}

// FillRunRecord populates fields on a RunRecord representing the run metadata.
func (metadata *RunMetadata) FillRunRecord(record *spb.RunRecord) {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	panic("TODO: Unimplemented.")
}

// RunPath returns the run's entity, project and run ID.
func (metadata *RunMetadata) RunPath() runbranch.RunPath {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	panic("TODO: Unimplemented.")
}

// ConfigYAML returns the run's config as a YAML string.
func (metadata *RunMetadata) ConfigYAML() ([]byte, error) {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	panic("TODO: Unimplemented.")
}

// ConfigMap returns a copy of the run's config as nested maps.
func (metadata *RunMetadata) ConfigMap() map[string]any {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	panic("TODO: Unimplemented.")
}

func (metadata *RunMetadata) StartTime() time.Time {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	panic("TODO: Unimplemented.")
}

func (metadata *RunMetadata) DisplayName() string {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	panic("TODO: Unimplemented.")
}

func (metadata *RunMetadata) FileStreamOffsets() filestream.FileStreamOffsetMap {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	panic("TODO: Unimplemented.")
}

// Finish uploads any remaining changes and ends the uploading goroutine.
func (metadata *RunMetadata) Finish() {
	select {
	case <-metadata.done:
		return

	// Continue only if not already done.
	default:
	}

	close(metadata.done)
	metadata.wg.Wait()
}

// syncPeriodically uploads changes in a loop.
func (metadata *RunMetadata) syncPeriodically() {
	// TODO: Loop forever, uploading changes as they arrive.
	//   Exit when the done channel is closed, flushing one more time.
	panic("TODO: Unimplemented.")
}

// lockedDoUpsert performs an UpsertBucket request to upload the current
// metadata.
//
// The mutex must be held. It is temporarily unlocked during the request.
func (metadata *RunMetadata) lockedDoUpsert(
	ctx context.Context,
) (*gql.UpsertBucketResponse, error) {
	if metadata.graphqlClientOrNil == nil {
		return nil, errors.New("runmetadata: cannot upsert when offline")
	}

	metadata.mu.Unlock()
	defer metadata.mu.Lock()

	// Use a special retry policy for UpsertBucket requests.
	ctx = context.WithValue(
		ctx,
		clients.CtxRetryPolicyKey,
		clients.UpsertBucketRetryPolicy,
	)

	_ = ctx
	panic("TODO: gql.UpsertBucket()")
}

// lockedUpdateFromUpsert updates metadata based on the response from
// the server.
//
// The mutex must be held.
func (metadata *RunMetadata) lockedUpdateFromUpsert(
	response *gql.UpsertBucketResponse,
) {
	panic("TODO: Unimplemented.")
}
