// Package runupserter manages run data that's uploaded via UpsertBucket.
package runupserter

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
	"github.com/wandb/wandb/core/internal/runenvironment"
	"github.com/wandb/wandb/core/internal/runmetric"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
)

// RunUpserter manages and syncs info about a run that's usually set on init and
// rarely changed.
//
// The RunUpserter object makes "UpsertBucket" requests when values change,
// debouncing them to avoid rapid-fire network requests.
type RunUpserter struct {
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

	params      *runbranch.RunParams
	config      *runconfig.RunConfig
	telemetry   *spb.TelemetryRecord
	metrics     *runmetric.RunConfigMetrics
	environment *runenvironment.RunEnvironment
}

type RunUpserterParams struct {
	DebounceDelay waiting.Delay

	ClientID           string
	Settings           *settings.Settings
	BeforeRunEndCtx    context.Context
	Operations         *wboperation.WandbOperations
	FeatureProvider    *featurechecker.ServerFeaturesCache
	GraphqlClientOrNil graphql.Client
	Logger             *observability.CoreLogger
}

func (params *RunUpserterParams) panicIfNotFilled() {
	switch {
	case params.DebounceDelay == nil:
		panic("runupserter: DebounceDelay is nil")
	case params.Settings == nil:
		panic("runupserter: Settings is nil")
	case params.BeforeRunEndCtx == nil:
		panic("runupserter: BeforeRunEndCtx is nil")
	case params.FeatureProvider == nil:
		panic("runupserter: FeatureProvider is nil")
	case params.Logger == nil:
		panic("runupserter: Logger is nil")
	}
}

// InitRun upserts a new run and returns it.
//
// This function blocks until the run is created.
//
// The returned error may wrap a RunUpdateError.
func InitRun(
	record *spb.Record,
	params RunUpserterParams,
) (*RunUpserter, error) {
	params.panicIfNotFilled()

	runRecord := record.GetRun()
	if runRecord == nil {
		panic("runupserter: RunRecord is nil")
	}

	// Initialize run environment info.
	environment := runenvironment.New(params.ClientID)

	// Initialize the run config.
	config := runconfig.New()
	config.ApplyChangeRecord(runRecord.Config,
		func(err error) {
			params.Logger.Error(
				"runupserter: error updating config",
				"error", err,
			)
		})
	telemetry := &spb.TelemetryRecord{}
	proto.Merge(telemetry, runRecord.Telemetry)
	telemetry.CoreVersion = version.Version
	config.AddInternalData(
		telemetry,
		make([]map[string]any, 0),
		environment.ToRunConfigData(),
	)

	// Initialize the run metrics.
	enableServerExpandedMetrics := params.Settings.IsEnableServerSideExpandGlobMetrics()
	if enableServerExpandedMetrics && !params.FeatureProvider.GetFeature(
		spb.ServerFeature_EXPAND_DEFINED_METRIC_GLOBS,
	).Enabled {
		params.Logger.Warn(
			"runupserter: server does not expand metric globs" +
				" but the x_server_side_expand_glob_metrics setting is set;" +
				" ignoring")
		enableServerExpandedMetrics = false
	}
	metrics := runmetric.NewRunConfigMetrics(enableServerExpandedMetrics)

	// Initialize other run metadata.
	runParams := runbranch.NewRunParams(runRecord, params.Settings)

	upserter := &RunUpserter{
		debounceDelay: params.DebounceDelay,

		settings:           params.Settings,
		beforeRunEndCtx:    params.BeforeRunEndCtx,
		operations:         params.Operations,
		graphqlClientOrNil: params.GraphqlClientOrNil,
		logger:             params.Logger,

		done:  make(chan struct{}),
		dirty: make(chan struct{}, 1),

		params:      runParams,
		config:      config,
		telemetry:   telemetry,
		metrics:     metrics,
		environment: environment,
	}

	operation := upserter.operations.New("creating run")
	defer operation.Finish()
	ctx := operation.Context(upserter.beforeRunEndCtx)

	// If resuming, rewinding or forking, we need to modify metadata
	// in special ways before upserting the run.
	//
	// There must be no UpsertBucket requests until the branching requests
	// finish. Specifically, when rewinding, RewindRun must complete and we
	// must use the updated config returned by the backend on the first
	// UpsertBucket request.
	branchPoint := runRecord.BranchPoint
	switch {
	case params.Settings.GetResume() != "":
		err := upserter.updateMetadataForResume(params.Settings.GetResume())

		if err != nil {
			return nil, runUpdateErrorFromBranchError(err)
		}

	case branchPoint != nil && branchPoint.GetRun() == runRecord.RunId:
		// Branching a run from an earlier point in its history is rewinding.
		err := upserter.updateMetadataForRewind(branchPoint)

		if err != nil {
			return nil, runUpdateErrorFromBranchError(err)
		}

	case branchPoint != nil && branchPoint.GetRun() != "":
		// Creating a new run by branching is forking.
		err := upserter.updateMetadataForFork(branchPoint)

		if err != nil {
			return nil, runUpdateErrorFromBranchError(err)
		}
	}

	// If we're offline, skip upserting.
	if upserter.graphqlClientOrNil == nil {
		return upserter, nil
	}

	upserter.mu.Lock()
	defer upserter.mu.Unlock()

	// Upsert the run.
	response, err := upserter.lockedDoUpsert(
		ctx,
		/*uploadParams=*/ true,
		/*uploadConfig=*/ true,
	)

	if err != nil {
		return nil, &RunUpdateError{
			UserMessage: fmt.Sprintf("Error uploading run: %v", err),
			Cause:       err,
			Code:        spb.ErrorInfo_COMMUNICATION,
		}
	}

	// Fill some metadata based on the server response.
	upserter.lockedUpdateFromUpsert(response)

	// Begin processing updates.
	upserter.wg.Add(1)
	go func() {
		defer upserter.wg.Done()
		upserter.syncPeriodically()
	}()

	return upserter, nil
}

// Update schedules an update to some part of the run metadata.
func (upserter *RunUpserter) Update(runRecord *spb.RunRecord) {
	upserter.mu.Lock()
	defer upserter.mu.Unlock()

	upserter.params.Update(runRecord, upserter.settings)

	upserter.isParamsDirty = true
	upserter.signalDirty()
}

// UpdateConfig schedules an update to the run's config.
func (upserter *RunUpserter) UpdateConfig(config *spb.ConfigRecord) {
	upserter.mu.Lock()
	defer upserter.mu.Unlock()

	upserter.config.ApplyChangeRecord(config,
		func(err error) {
			upserter.logger.CaptureError(
				fmt.Errorf("runupserter: error updating config: %v", err))
		})

	upserter.isConfigDirty = true
	upserter.signalDirty()
}

// UpdateTelemetry schedules an update to the run's telemetry.
func (upserter *RunUpserter) UpdateTelemetry(telemetry *spb.TelemetryRecord) {
	upserter.mu.Lock()
	defer upserter.mu.Unlock()

	proto.Merge(upserter.telemetry, telemetry)

	upserter.config.AddInternalData(
		upserter.telemetry,
		upserter.metrics.ToRunConfigData(),
		upserter.environment.ToRunConfigData(),
	)

	upserter.isConfigDirty = true
	upserter.signalDirty()
}

// UpdateEnvironment schedules an update to the run's metadata in the config.
func (upserter *RunUpserter) UpdateEnvironment(metadata *spb.EnvironmentRecord) {
	upserter.mu.Lock()
	defer upserter.mu.Unlock()

	upserter.environment.ProcessRecord(metadata)

	upserter.config.AddInternalData(
		upserter.telemetry,
		upserter.metrics.ToRunConfigData(),
		upserter.environment.ToRunConfigData(),
	)

	upserter.isConfigDirty = true
	upserter.signalDirty()
}

// UpdateMetrics schedules an update to the run's metrics in the config.
func (upserter *RunUpserter) UpdateMetrics(metric *spb.MetricRecord) {
	upserter.mu.Lock()
	defer upserter.mu.Unlock()

	// Skip uploading expanded metrics if the server expands them itself.
	if upserter.metrics.IsServerExpandGlobMetrics() &&
		metric.GetExpandedFromGlob() {
		return
	}

	err := upserter.metrics.ProcessRecord(metric)
	if err != nil {
		upserter.logger.CaptureError(
			fmt.Errorf("runupserter: failed to process metric: %v", err))
		return
	}

	upserter.config.AddInternalData(
		upserter.telemetry,
		upserter.metrics.ToRunConfigData(),
		upserter.environment.ToRunConfigData(),
	)

	upserter.isConfigDirty = true
	upserter.signalDirty()
}

// FillRunRecord populates fields on a RunRecord representing the run metadata.
func (upserter *RunUpserter) FillRunRecord(record *spb.RunRecord) {
	upserter.mu.Lock()
	defer upserter.mu.Unlock()
	upserter.params.SetOnProto(record)

	record.Config = &spb.ConfigRecord{}
	for key, value := range upserter.config.CloneTree() {
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
func (upserter *RunUpserter) RunPath() runbranch.RunPath {
	upserter.mu.Lock()
	defer upserter.mu.Unlock()
	return runbranch.RunPath{
		Entity:  upserter.params.Entity,
		Project: upserter.params.Project,
		RunID:   upserter.params.RunID,
	}
}

// ConfigYAML returns the run's config as a YAML string.
func (upserter *RunUpserter) ConfigYAML() ([]byte, error) {
	upserter.mu.Lock()
	defer upserter.mu.Unlock()
	return upserter.config.Serialize(runconfig.FormatYaml)
}

// ConfigMap returns a copy of the run's config as nested maps.
func (upserter *RunUpserter) ConfigMap() map[string]any {
	upserter.mu.Lock()
	defer upserter.mu.Unlock()
	return upserter.config.CloneTree()
}

// EnvironmentJSON returns the run's environment info snapshot as a JSON string.
func (upserter *RunUpserter) EnvironmentJSON() ([]byte, error) {
	upserter.mu.Lock()
	defer upserter.mu.Unlock()
	return upserter.environment.ToJSON()
}

func (upserter *RunUpserter) StartTime() time.Time {
	upserter.mu.Lock()
	defer upserter.mu.Unlock()
	return upserter.params.StartTime
}

func (upserter *RunUpserter) DisplayName() string {
	upserter.mu.Lock()
	defer upserter.mu.Unlock()
	return upserter.params.DisplayName
}

func (upserter *RunUpserter) FileStreamOffsets() filestream.FileStreamOffsetMap {
	upserter.mu.Lock()
	defer upserter.mu.Unlock()
	return upserter.params.FileStreamOffset
}

// Finish uploads any remaining changes and ends the uploading goroutine.
func (upserter *RunUpserter) Finish() {
	select {
	case <-upserter.done:
		return

	// Continue only if not already done.
	default:
	}

	close(upserter.done)
	upserter.wg.Wait()
}

// signalDirty pushes to the dirty channel to trigger an upload.
//
// The corresponding flags should be updated separately.
func (upserter *RunUpserter) signalDirty() {
	select {
	case upserter.dirty <- struct{}{}:
	default:
	}
}

// updateMetadataForResume updates run metadata based on the existing run
// that's being resumed.
func (upserter *RunUpserter) updateMetadataForResume(
	resumeSetting string,
) error {
	if upserter.graphqlClientOrNil == nil {
		// Ignore the resume mode when offline.
		//
		// A warning is printed by the client during wandb.init().
		//
		// resume="auto" is always OK and is handled by the client.
		return nil
	}

	return runbranch.NewResumeBranch(
		upserter.beforeRunEndCtx,
		upserter.graphqlClientOrNil,
		resumeSetting,
	).UpdateForResume(
		upserter.params,
		upserter.config,
	)
}

// updateMetadataForRewind updates run metadata based on the existing run
// that's being rewound.
func (upserter *RunUpserter) updateMetadataForRewind(
	rewindSetting *spb.BranchPoint,
) error {
	return runbranch.NewRewindBranch(
		upserter.beforeRunEndCtx,
		upserter.graphqlClientOrNil,
		rewindSetting.Run,
		rewindSetting.Metric,
		rewindSetting.Value,
	).UpdateForRewind(
		upserter.params,
		upserter.config,
	)
}

// updateMetadataForFork updates configures run metadata for a forked run.
func (upserter *RunUpserter) updateMetadataForFork(
	forkSetting *spb.BranchPoint,
) error {
	return runbranch.NewForkBranch(
		forkSetting.Run,
		forkSetting.Metric,
		forkSetting.Value,
	).UpdateForFork(upserter.params)
}

// syncPeriodically uploads changes in a loop.
func (upserter *RunUpserter) syncPeriodically() {
	for {
		select {
		case <-upserter.dirty:
			upserter.debounceAndUploadChanges()

		case <-upserter.done:
			upserter.debounceAndUploadChanges()
			return
		}
	}
}

// debounce accumulates changes for some time to avoid rapid-fire updates.
//
// It is immediate if finishing.
func (upserter *RunUpserter) debounce() {
	delay, cancel := upserter.debounceDelay.Wait()
	defer cancel()

	select {
	case <-delay:
	case <-upserter.done:
	}
}

// debounceAndUploadChanges uploads any changes to the run's metadata.
func (upserter *RunUpserter) debounceAndUploadChanges() {
	operation := upserter.operations.New("updating run metadata")
	defer operation.Finish()
	ctx := operation.Context(upserter.beforeRunEndCtx)

	upserter.debounce()

	upserter.mu.Lock()
	defer upserter.mu.Unlock()

	if !upserter.isParamsDirty && !upserter.isConfigDirty {
		return
	}

	_, err := upserter.lockedDoUpsert(
		ctx,
		upserter.isParamsDirty,
		upserter.isConfigDirty,
	)

	if err != nil {
		upserter.logger.Error(
			"runupserter: failed to upload changes",
			"error", err,
		)
	}
}

// serializeConfig returns the serialized run config.
//
// If an error happens, it is logged an an empty string is returned.
func (upserter *RunUpserter) serializeConfig() string {
	serializedConfig, err := upserter.config.Serialize(runconfig.FormatJson)

	if err != nil {
		upserter.logger.Error(
			"runupserter: failed to serialize config",
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
func (upserter *RunUpserter) lockedDoUpsert(
	ctx context.Context,
	uploadParams, uploadConfig bool,
) (*gql.UpsertBucketResponse, error) {
	if upserter.graphqlClientOrNil == nil {
		return nil, errors.New("runupserter: cannot upsert when offline")
	}

	// Clear dirty state.
	select {
	case <-upserter.dirty:
	default:
	}
	upserter.isParamsDirty = !uploadParams && upserter.isParamsDirty
	upserter.isConfigDirty = !uploadConfig && upserter.isConfigDirty

	name := nullify.NilIfZero(upserter.params.RunID)
	project := nullify.NilIfZero(upserter.params.Project)
	entity := nullify.NilIfZero(upserter.params.Entity)

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
		storageID = nullify.NilIfZero(upserter.params.StorageID)
		groupName = nullify.NilIfZero(upserter.params.GroupName)
		displayName = nullify.NilIfZero(upserter.params.DisplayName)
		notes = nullify.NilIfZero(upserter.params.Notes)
		commit = nullify.NilIfZero(upserter.params.Commit)
		host = nullify.NilIfZero(upserter.params.Host)
		program = nullify.NilIfZero(upserter.params.Program)
		repo = nullify.NilIfZero(upserter.params.RemoteURL)
		jobType = nullify.NilIfZero(upserter.params.JobType)
		sweepID = nullify.NilIfZero(upserter.params.SweepID)
		tags = slices.Clone(upserter.params.Tags)
	}

	var config *string
	if uploadConfig {
		config = nullify.NilIfZero(upserter.serializeConfig())
	}

	upserter.mu.Unlock()
	defer upserter.mu.Lock()

	// Use a special retry policy for UpsertBucket requests.
	ctx = context.WithValue(
		ctx,
		clients.CtxRetryPolicyKey,
		clients.UpsertBucketRetryPolicy,
	)

	return gql.UpsertBucket(
		ctx,
		upserter.graphqlClientOrNil,
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
func (upserter *RunUpserter) lockedUpdateFromUpsert(
	response *gql.UpsertBucketResponse,
) {
	if response.GetUpsertBucket() == nil ||
		response.GetUpsertBucket().GetBucket() == nil {
		upserter.logger.Error("runupserter: upsert bucket response empty")
		return
	}

	bucket := response.GetUpsertBucket().GetBucket()

	upserter.params.StorageID = bucket.GetId()
	upserter.params.RunID = bucket.GetName()
	upserter.params.DisplayName = nullify.ZeroIfNil(bucket.GetDisplayName())
	upserter.params.SweepID = nullify.ZeroIfNil(bucket.GetSweepName())

	if lineCount := nullify.ZeroIfNil(bucket.GetHistoryLineCount()); lineCount > 0 {
		upserter.params.FileStreamOffset = filestream.FileStreamOffsetMap{
			filestream.HistoryChunk: lineCount,
		}
	}

	if project := bucket.GetProject(); project == nil {
		upserter.logger.Error("runupserter: upsert bucket project is nil")
	} else {
		entity := project.GetEntity()

		upserter.params.Entity = entity.GetName()
		upserter.params.Project = project.GetName()
	}
}
