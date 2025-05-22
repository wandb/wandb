// Package runmetadata manages run data that's uploaded via UpsertBucket.
package runmetadata

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"sync"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/nullify"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runbranch"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/internal/runmetric"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
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

	// dirty is a 1-buffered chan used to indicate that there are changes to
	// upload.
	dirty         chan struct{}
	isParamsDirty bool // whether params has un-uploaded changes
	isConfigDirty bool // whether config has un-uploaded changes

	params    *runbranch.RunParams
	config    *runconfig.RunConfig
	telemetry *spb.TelemetryRecord
	metrics   *runmetric.RunConfigMetrics
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

	runRecord := record.GetRun()
	if runRecord == nil {
		panic("runmetadata: RunRecord is nil")
	}

	// Initialize the run config.
	config := runconfig.New()
	config.ApplyChangeRecord(runRecord.Config,
		func(err error) {
			params.Logger.Error(
				"runmetadata: error updating config",
				"error", err,
			)
		})
	telemetry := &spb.TelemetryRecord{}
	proto.Merge(telemetry, runRecord.Telemetry)
	telemetry.CoreVersion = version.Version
	config.AddTelemetryAndMetrics(
		telemetry,
		make([]map[string]any, 0),
	)

	// Initialize the run metrics.
	enableServerExpandedMetrics := params.Settings.IsEnableServerSideExpandGlobMetrics()
	if enableServerExpandedMetrics && !params.FeatureProvider.GetFeature(
		spb.ServerFeature_EXPAND_DEFINED_METRIC_GLOBS,
	).Enabled {
		params.Logger.Warn(
			"runmetadata: server does not expand metric globs" +
				" but the x_server_side_expand_glob_metrics setting is set;" +
				" ignoring")
		enableServerExpandedMetrics = false
	}
	metrics := runmetric.NewRunConfigMetrics(enableServerExpandedMetrics)

	// Initialize other run metadata.
	runParams := runbranch.NewRunParams(runRecord, params.Settings)

	metadata := &RunMetadata{
		debounceDelay: params.DebounceDelay,

		settings:           params.Settings,
		beforeRunEndCtx:    params.BeforeRunEndCtx,
		operations:         params.Operations,
		graphqlClientOrNil: params.GraphqlClientOrNil,
		logger:             params.Logger,

		done:  make(chan struct{}),
		dirty: make(chan struct{}, 1),

		params:    runParams,
		config:    config,
		telemetry: telemetry,
		metrics:   metrics,
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
	response, err := metadata.lockedDoUpsert(
		ctx,
		/*uploadParams=*/ true,
		/*uploadConfig=*/ true,
	)

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

	metadata.params.Update(runRecord, metadata.settings)

	metadata.isParamsDirty = true
	metadata.signalDirty()
}

// UpdateConfig schedules an update to the run's config.
func (metadata *RunMetadata) UpdateConfig(config *spb.ConfigRecord) {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()

	metadata.config.ApplyChangeRecord(config,
		func(err error) {
			metadata.logger.CaptureError(
				fmt.Errorf("runmetadata: error updating config: %v", err))
		})

	metadata.isConfigDirty = true
	metadata.signalDirty()
}

// UpdateTelemetry schedules an update to the run's telemetry.
func (metadata *RunMetadata) UpdateTelemetry(telemetry *spb.TelemetryRecord) {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()

	proto.Merge(metadata.telemetry, telemetry)

	metadata.config.AddTelemetryAndMetrics(
		metadata.telemetry,
		metadata.metrics.ToRunConfigData(),
	)

	metadata.isConfigDirty = true
	metadata.signalDirty()
}

// UpdateMetrics schedules an update to the run's metrics in the config.
func (metadata *RunMetadata) UpdateMetrics(metric *spb.MetricRecord) {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()

	// Skip uploading expanded metrics if the server expands them itself.
	if metadata.metrics.IsServerExpandGlobMetrics() &&
		metric.GetExpandedFromGlob() {
		return
	}

	err := metadata.metrics.ProcessRecord(metric)
	if err != nil {
		metadata.logger.CaptureError(
			fmt.Errorf("runmetadata: failed to process metric: %v", err))
		return
	}

	metadata.config.AddTelemetryAndMetrics(
		metadata.telemetry,
		metadata.metrics.ToRunConfigData(),
	)

	metadata.isConfigDirty = true
	metadata.signalDirty()
}

// FillRunRecord populates fields on a RunRecord representing the run metadata.
func (metadata *RunMetadata) FillRunRecord(record *spb.RunRecord) {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	metadata.params.SetOnProto(record)

	record.Config = &spb.ConfigRecord{}
	for key, value := range metadata.config.CloneTree() {
		valueJSON, _ := simplejsonext.MarshalToString(map[string]any{
			"value": value,
		})

		record.Config.Update = append(record.Config.Update,
			&spb.ConfigItem{
				Key:       key,
				ValueJson: valueJSON,
			})
	}
}

// RunPath returns the run's entity, project and run ID.
func (metadata *RunMetadata) RunPath() runbranch.RunPath {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	return runbranch.RunPath{
		Entity:  metadata.params.Entity,
		Project: metadata.params.Project,
		RunID:   metadata.params.RunID,
	}
}

// ConfigYAML returns the run's config as a YAML string.
func (metadata *RunMetadata) ConfigYAML() ([]byte, error) {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	return metadata.config.Serialize(runconfig.FormatYaml)
}

// ConfigMap returns a copy of the run's config as nested maps.
func (metadata *RunMetadata) ConfigMap() map[string]any {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	return metadata.config.CloneTree()
}

func (metadata *RunMetadata) StartTime() time.Time {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	return metadata.params.StartTime
}

func (metadata *RunMetadata) DisplayName() string {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	return metadata.params.DisplayName
}

func (metadata *RunMetadata) FileStreamOffsets() filestream.FileStreamOffsetMap {
	metadata.mu.Lock()
	defer metadata.mu.Unlock()
	return metadata.params.FileStreamOffset
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

// signalDirty pushes to the dirty channel to trigger an upload.
//
// The corresponding flags should be updated separately.
func (metadata *RunMetadata) signalDirty() {
	select {
	case metadata.dirty <- struct{}{}:
	default:
	}
}

// syncPeriodically uploads changes in a loop.
func (metadata *RunMetadata) syncPeriodically() {
	for {
		select {
		case <-metadata.dirty:
			metadata.debounceAndUploadChanges()

		case <-metadata.done:
			metadata.debounceAndUploadChanges()
			return
		}
	}
}

// debounce accumulates changes for some time to avoid rapid-fire updates.
//
// It is immediate if finishing.
func (metadata *RunMetadata) debounce() {
	delay, cancel := metadata.debounceDelay.Wait()
	defer cancel()

	select {
	case <-delay:
	case <-metadata.done:
	}
}

// debounceAndUploadChanges uploads any changes to the run's metadata.
func (metadata *RunMetadata) debounceAndUploadChanges() {
	operation := metadata.operations.New("updating run metadata")
	defer operation.Finish()
	ctx := operation.Context(metadata.beforeRunEndCtx)

	metadata.debounce()

	metadata.mu.Lock()
	defer metadata.mu.Unlock()

	if !metadata.isParamsDirty && !metadata.isConfigDirty {
		return
	}

	_, err := metadata.lockedDoUpsert(
		ctx,
		metadata.isParamsDirty,
		metadata.isConfigDirty,
	)

	if err != nil {
		metadata.logger.Error(
			"runmetadata: failed to upload changes",
			"error", err,
		)
	}
}

// serializeConfig returns the serialized run config.
//
// If an error happens, it is logged an an empty string is returned.
func (metadata *RunMetadata) serializeConfig() string {
	serializedConfig, err := metadata.config.Serialize(runconfig.FormatJson)

	if err != nil {
		metadata.logger.Error(
			"runmetadata: failed to serialize config",
			"error", err,
		)
		return ""
	} else {
		return string(serializedConfig)
	}
}

// lockedDoUpsert performs an UpsertBucket request to upload the current
// metadata.
//
// The mutex must be held. It is temporarily unlocked during the request.
func (metadata *RunMetadata) lockedDoUpsert(
	ctx context.Context,
	uploadParams, uploadConfig bool,
) (*gql.UpsertBucketResponse, error) {
	if metadata.graphqlClientOrNil == nil {
		return nil, errors.New("runmetadata: cannot upsert when offline")
	}

	// Clear dirty state.
	select {
	case <-metadata.dirty:
	default:
	}
	metadata.isParamsDirty = !uploadParams && metadata.isParamsDirty
	metadata.isConfigDirty = !uploadConfig && metadata.isConfigDirty

	name := nullify.NilIfZero(metadata.params.RunID)
	project := nullify.NilIfZero(metadata.params.Project)
	entity := nullify.NilIfZero(metadata.params.Entity)

	// NOTE: The only reason not to upload these short strings on every request
	//   is because of shared mode, where there may be multiple machines writing
	//   to the same run. We wouldn't want updating the config on one machine to
	//   clear the run tags set by another.

	var storageID *string
	var groupName *string
	var displayName *string
	var notes *string
	var commit *string
	var host *string
	var program *string
	var repo *string
	var jobType *string
	var sweepID *string
	var tags []string
	if uploadParams {
		storageID = nullify.NilIfZero(metadata.params.StorageID)
		groupName = nullify.NilIfZero(metadata.params.GroupName)
		displayName = nullify.NilIfZero(metadata.params.DisplayName)
		notes = nullify.NilIfZero(metadata.params.Notes)
		commit = nullify.NilIfZero(metadata.params.Commit)
		host = nullify.NilIfZero(metadata.params.Host)
		program = nullify.NilIfZero(metadata.params.Program)
		repo = nullify.NilIfZero(metadata.params.RemoteURL)
		jobType = nullify.NilIfZero(metadata.params.JobType)
		sweepID = nullify.NilIfZero(metadata.params.SweepID)
		tags = slices.Clone(metadata.params.Tags)
	}

	var config *string
	if uploadConfig {
		config = nullify.NilIfZero(metadata.serializeConfig())
	}

	metadata.mu.Unlock()
	defer metadata.mu.Lock()

	// Use a special retry policy for UpsertBucket requests.
	ctx = context.WithValue(
		ctx,
		clients.CtxRetryPolicyKey,
		clients.UpsertBucketRetryPolicy,
	)

	return gql.UpsertBucket(
		ctx,
		metadata.graphqlClientOrNil,
		storageID,
		name,
		project,
		entity,
		groupName,
		nil, // description
		displayName,
		notes,
		commit,
		config,
		host,
		nil, // debug
		program,
		repo,
		jobType,
		nil, // state
		sweepID,
		tags,
		nil, // summaryMetrics
	)
}

// lockedUpdateFromUpsert updates metadata based on the response from
// the server.
//
// The mutex must be held.
func (metadata *RunMetadata) lockedUpdateFromUpsert(
	response *gql.UpsertBucketResponse,
) {
	if response.GetUpsertBucket() == nil ||
		response.GetUpsertBucket().GetBucket() == nil {
		metadata.logger.Error("runmetadata: upsert bucket response empty")
		return
	}

	bucket := response.GetUpsertBucket().GetBucket()

	metadata.params.StorageID = bucket.GetId()
	metadata.params.RunID = bucket.GetName()
	metadata.params.DisplayName = nullify.ZeroIfNil(bucket.GetDisplayName())
	metadata.params.SweepID = nullify.ZeroIfNil(bucket.GetSweepName())

	if lineCount := nullify.ZeroIfNil(bucket.GetHistoryLineCount()); lineCount > 0 {
		metadata.params.FileStreamOffset = filestream.FileStreamOffsetMap{
			filestream.HistoryChunk: lineCount,
		}
	}

	if project := bucket.GetProject(); project == nil {
		metadata.logger.Error("runmetadata: upsert bucket project is nil")
	} else {
		entity := project.GetEntity()

		metadata.params.Entity = entity.GetName()
		metadata.params.Project = project.GetName()
	}
}
