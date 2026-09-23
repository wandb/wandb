package leet

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"reflect"
	"strings"
	"sync"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/Khan/genqlient/graphql"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/httplayers"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhistoryreader"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/ffi"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	parquetBatchScanSize = 100
	unknownMaxStep       = -1

	// remotePollInterval is how often LEET asks the W&B backend for new
	// runs and for new data from live runs.
	remotePollInterval = 15 * time.Second
)

// RunInfo is the run metadata fetched from the W&B backend.
type RunInfo struct {
	// entity is the entity name who the run belongs to.
	entity string

	// project is the project name where the run is stored.
	project string

	// runId is the unique identifier for the run.
	runId string

	// runSummary is the summary of the run.
	runSummary map[string]any

	// displayName is the display name of the run.
	displayName string

	notes  string
	tags   []string
	config *spb.ConfigRecord

	// runState is the authoritative state returned by the W&B backend.
	runState RunState
}

// newRunInfo converts a run fetched from the W&B backend.
//
// A config that fails to parse is logged and left out.
func newRunInfo(
	entity, project string,
	run *gql.LeetRun,
	logger *observability.CoreLogger,
) *RunInfo {
	config, err := remoteConfig(run.Config)
	if err != nil {
		logger.Warn("leet: failed to parse remote run config", "run", run.Name, "error", err)
	}
	return &RunInfo{
		entity:      entity,
		project:     project,
		runId:       run.Name,
		displayName: run.DisplayName,
		notes:       run.Notes,
		tags:        run.Tags,
		config:      config,
		runState:    remoteRunState(run.State),
	}
}

// remoteConfig converts a run config from the W&B backend, which maps each
// key to {"value": ...}, to a ConfigRecord.
func remoteConfig(configJSON string) (*spb.ConfigRecord, error) {
	if configJSON == "" {
		return nil, nil
	}
	config, err := simplejsonext.UnmarshalObjectString(configJSON)
	if err != nil {
		return nil, err
	}

	record := &spb.ConfigRecord{}
	for key, item := range config {
		entry, _ := item.(map[string]any)
		value, ok := entry["value"]
		if !ok {
			continue
		}
		valueJSON, err := simplejsonext.MarshalToString(value)
		if err != nil {
			return nil, err
		}
		record.Update = append(record.Update, &spb.ConfigItem{Key: key, ValueJson: valueJSON})
	}
	return record, nil
}

// runPath identifies the run in messages and as a metrics series.
func (ri *RunInfo) runPath() string {
	return ri.entity + "/" + ri.project + "/" + ri.runId
}

// runMsg describes the run the way a transaction log's Run record would.
func (ri *RunInfo) runMsg() RunMsg {
	state := ri.runState
	return RunMsg{
		RunPath:     ri.runPath(),
		ID:          ri.runId,
		Entity:      ri.entity,
		Project:     ri.project,
		DisplayName: ri.displayName,
		Notes:       ri.notes,
		Tags:        ri.tags,
		Config:      ri.config,
		State:       &state,
	}
}

// historyStepReader pages through a remote run's history.
type historyStepReader interface {
	GetHistorySteps(ctx context.Context, minStep, maxStep int64) ([]parquet.KeyValueList, error)
	Release()
}

// ParquetHistorySource reads a remote run's history from its parquet
// exports on the W&B backend.
//
// TODO: resolve custom x-axes like LevelDBHistorySource does for
// Record_Metric. For remote runs the define_metric definitions live in
// the run config under _wandb.m, which is not fetched yet.
//
// Implements HistorySource.
type ParquetHistorySource struct {
	logger *observability.CoreLogger

	// ctx is cancelled by Close to abort in-flight requests
	// and prevent reads after shutdown.
	ctx    context.Context
	cancel context.CancelFunc
	close  sync.Once

	// readerDone is a flag to indicate if the reader is done.
	readerDone bool

	// reader is the currently active history reader.
	reader historyStepReader

	// liveReader reads new history directly from the W&B backend.
	liveReader historyStepReader

	// usingLiveReader indicates that ownership has moved to liveReader.
	usingLiveReader bool

	// graphqlClient is used to refresh metadata for live remote runs.
	graphqlClient graphql.Client

	// runPath identifies the remote run in messages.
	runPath string

	// currentStep is the current step of the reader.
	currentStep int64

	// maxKnownStep is the last step logged by the run, extracted from the
	// run summary's "_step" field. It is used as a termination bound once
	// the backend reports a terminal state. A negative value means the
	// summary did not provide a bound.
	maxKnownStep int64

	// initialMaxStep is the summary step observed when the source was created.
	// While the run is live, it bounds the boot load before subsequent reads
	// switch to polling for live history.
	initialMaxStep int64

	// bootLoadComplete indicates that the initial summary range has been read.
	bootLoadComplete bool

	// runInfo is the information about the run. Never nil.
	runInfo *RunInfo
}

// newParquetHistorySource creates a new ParquetHistorySource.
//
// runInfo must be non-nil.
func newParquetHistorySource(
	ctx context.Context,
	runInfo *RunInfo,
	reader historyStepReader,
	liveReader historyStepReader,
	logger *observability.CoreLogger,
	graphqlClient graphql.Client,
) *ParquetHistorySource {
	ctx, cancel := context.WithCancel(ctx)
	initialMaxStep := maxStepFromSummary(runInfo.runSummary)

	return &ParquetHistorySource{
		logger:           logger,
		ctx:              ctx,
		cancel:           cancel,
		runPath:          runInfo.runPath(),
		maxKnownStep:     initialMaxStep,
		initialMaxStep:   initialMaxStep,
		bootLoadComplete: initialMaxStep < 0,
		runInfo:          runInfo,
		reader:           reader,
		liveReader:       liveReader,
		graphqlClient:    graphqlClient,
	}
}

// InitializeParquetHistorySource returns a tea.Cmd that initializes a
// ParquetHistorySource for a remote run.
func InitializeParquetHistorySource(
	ctx context.Context,
	runParams *RemoteRunParams,
	logger *observability.CoreLogger,
) tea.Cmd {
	return func() tea.Msg {
		clients, err := newRemoteClients(runParams.BaseURL, logger)
		if err != nil {
			return ErrorMsg{Err: err}
		}
		source, err := clients.openRun(
			ctx, runParams.Entity, runParams.Project, runParams.RunID, logger)
		if err != nil {
			return ErrorMsg{Err: err}
		}
		return InitMsg{Source: source}
	}
}

// remoteClients talk to the W&B backend that hosts remote runs.
type remoteClients struct {
	graphql graphql.Client
	http    api.RetryableClient
}

// newRemoteClients authenticates with the API key passed by the Python wrapper.
func newRemoteClients(
	baseURL string,
	logger *observability.CoreLogger,
) (*remoteClients, error) {
	apiKey := os.Getenv("WANDB_API_KEY")
	if apiKey == "" {
		return nil, errors.New("WANDB_API_KEY is not set")
	}

	s := settings.From(&spb.Settings{
		ApiKey:  wrapperspb.String(apiKey),
		BaseUrl: wrapperspb.String(baseURL),
	})
	apiURL := stream.BaseURLFromSettings(logger, s)
	credentialProvider := stream.CredentialsFromSettings(logger, s)

	return &remoteClients{
		graphql: stream.NewGraphQLClient(
			apiURL,
			"", /*clientID*/
			credentialProvider,
			logger,
			&observability.Peeker{},
			s,
		),
		http: api.NewClient(api.ClientOptions{
			RetryMax:        3,
			RetryWaitMin:    1 * time.Second,
			RetryWaitMax:    10 * time.Second,
			NonRetryTimeout: 10 * time.Second,
			Logger:          logger.Logger,
			PreRetryLayers:  httplayers.LimitTo(apiURL, credentialProvider),
		}),
	}, nil
}

// openRun loads a remote run's metadata and opens its history.
func (c *remoteClients) openRun(
	ctx context.Context,
	entity, project, runID string,
	logger *observability.CoreLogger,
) (*ParquetHistorySource, error) {
	runInfo, err := loadRunInfo(ctx, c.graphql, entity, project, runID, logger)
	if err != nil {
		return nil, err
	}

	rustArrowWrapper, err := ffi.NewRustArrowWrapper()
	if err != nil {
		return nil, err
	}

	reader, err := runhistoryreader.New(
		ctx,
		entity,
		project,
		runID,
		c.graphql,
		c.http,
		[]string{}, // keys
		false,      // useCache
		rustArrowWrapper,
	)
	if err != nil {
		return nil, err
	}
	liveReader := runhistoryreader.NewLiveDataReader(entity, project, runID, c.graphql, nil)

	return newParquetHistorySource(ctx, runInfo, reader, liveReader, logger, c.graphql), nil
}

// Read implements HistorySource.Read.
func (s *ParquetHistorySource) Read(
	chunkSize int,
	maxTimePerChunk time.Duration,
) (tea.Msg, error) {
	if s.readerDone {
		return nil, io.EOF
	}
	if err := s.ctx.Err(); err != nil {
		return nil, io.EOF
	}

	refreshed, err := s.refreshRunInfo()
	if err != nil {
		return nil, err
	}

	var msgs []tea.Msg
	if s.currentStep == 0 || refreshed {
		msgs = append(msgs, s.runInfo.runMsg(), s.summaryMsg())
	}

	chunk, err := s.readHistoryChunk(chunkSize, maxTimePerChunk)
	if err != nil {
		return nil, err
	}
	if len(chunk.histories) > 0 {
		msgs = append(msgs, concatenateHistory(chunk.histories, s.runPath))
	}

	// After the initial boot load, switch to live data reader.
	if !chunk.hasMore && s.runInfo.runState.mayBeLive() && !s.usingLiveReader {
		s.reader.Release()
		s.reader = s.liveReader
		s.usingLiveReader = true
	}

	return ChunkedBatchMsg{
		Msgs:     msgs,
		HasMore:  chunk.hasMore,
		Progress: chunk.progress,
	}, nil
}

// refreshRunInfo reloads the metadata of a run that may still be live and
// reports whether it did.
func (s *ParquetHistorySource) refreshRunInfo() (bool, error) {
	if !s.runInfo.runState.mayBeLive() || s.graphqlClient == nil {
		return false, nil
	}

	runInfo, err := loadRunInfo(
		s.ctx,
		s.graphqlClient,
		s.runInfo.entity,
		s.runInfo.project,
		s.runInfo.runId,
		s.logger,
	)
	if err != nil {
		return false, err
	}

	s.runInfo = runInfo
	s.maxKnownStep = maxStepFromSummary(runInfo.runSummary)
	return true, nil
}

type parquetHistoryChunk struct {
	histories []HistoryMsg
	hasMore   bool
	progress  int
}

func (s *ParquetHistorySource) readHistoryChunk(
	chunkSize int,
	maxTimePerChunk time.Duration,
) (parquetHistoryChunk, error) {
	chunk := parquetHistoryChunk{hasMore: true}

	bootLoadActive := s.runInfo.runState.mayBeLive() &&
		!s.bootLoadComplete &&
		s.initialMaxStep >= 0
	bootMaxStepExclusive := s.initialMaxStep + 1
	startTime := time.Now()
	for time.Since(startTime) < maxTimePerChunk &&
		chunk.progress < chunkSize {
		if s.finishTerminalRead() {
			chunk.hasMore = false
			break
		}

		nextStep := s.currentStep + int64(parquetBatchScanSize)
		if bootLoadActive && nextStep > bootMaxStepExclusive {
			nextStep = bootMaxStepExclusive
		}
		historySteps, err := s.reader.GetHistorySteps(
			s.ctx,
			s.currentStep,
			nextStep,
		)
		if err != nil {
			return parquetHistoryChunk{}, err
		}

		if len(historySteps) == 0 {
			if s.advanceAfterEmptyRead(
				nextStep,
				bootLoadActive,
				bootMaxStepExclusive,
			) {
				continue
			}
			chunk.hasMore = !s.readerDone && !s.bootLoadComplete
			break
		}

		s.advanceCurrentStep(historySteps, nextStep)
		chunk.histories = append(
			chunk.histories,
			parseParquetHistorySteps(historySteps, s.logger),
		)
		chunk.progress += len(historySteps)

		if bootLoadActive && s.currentStep >= bootMaxStepExclusive {
			s.bootLoadComplete = true
			chunk.hasMore = false
			break
		}

		if s.finishTerminalRead() {
			chunk.hasMore = false
			break
		}
	}

	return chunk, nil
}

func (s *ParquetHistorySource) finishTerminalRead() bool {
	if s.runInfo.runState.mayBeLive() ||
		s.maxKnownStep < 0 ||
		s.currentStep <= s.maxKnownStep {
		return false
	}

	s.readerDone = true
	return true
}

func (s *ParquetHistorySource) advanceCurrentStep(
	historySteps []parquet.KeyValueList,
	nextStep int64,
) {
	maxStep := historySteps[len(historySteps)-1].StepValue()
	if maxStep < s.currentStep {
		s.currentStep = nextStep
		return
	}
	s.currentStep = maxStep + 1
}

// advanceAfterEmptyRead advances across gaps during a bounded history scan.
// Once live polling begins, it keeps the current step so late-arriving data
// at that step is not skipped.
func (s *ParquetHistorySource) advanceAfterEmptyRead(
	nextStep int64,
	bootLoadActive bool,
	bootMaxStepExclusive int64,
) bool {
	if !s.runInfo.runState.mayBeLive() {
		if s.maxKnownStep < 0 {
			s.readerDone = true
			return false
		}

		s.currentStep = nextStep
		return true
	}

	if !bootLoadActive {
		return false
	}

	s.currentStep = nextStep
	s.bootLoadComplete = s.currentStep >= bootMaxStepExclusive
	return !s.bootLoadComplete
}

func (s *ParquetHistorySource) NextLiveReadCmd(
	readCmd tea.Cmd,
	hasMore bool,
) tea.Cmd {
	if hasMore {
		return readCmd
	}

	// A terminal run with no currently available data is fully drained.
	if !s.runInfo.runState.mayBeLive() {
		return nil
	}

	// The run is still live and there maybe more data to read.
	// Schedule a periodic read to check for new data.
	return tea.Tick(remotePollInterval, func(time.Time) tea.Msg {
		return readCmd()
	})
}

// Close implements HistorySource.Close.
func (s *ParquetHistorySource) Close() {
	s.close.Do(func() {
		s.cancel()
		s.reader.Release()
		s.liveReader.Release()
	})
}

// parseParquetHistorySteps converts a list of parquet.KeyValueList to a HistoryMsg.
func parseParquetHistorySteps(
	historySteps []parquet.KeyValueList,
	logger *observability.CoreLogger,
) HistoryMsg {
	h := HistoryMsg{
		Metrics: make(map[string]MetricData),
	}

	for _, historyStep := range historySteps {
		currentStep, err := getStepFromMetricsList(historyStep)
		if err != nil {
			logger.Warn(
				"parquet history source: failed to get current step",
				"error",
				err,
			)
			continue
		}

		for _, keyValue := range historyStep {
			if keyValue.Key == parquet.StepKey || strings.HasPrefix(keyValue.Key, "_") {
				continue
			}

			existing := h.Metrics[keyValue.Key]
			var value float64
			switch v := keyValue.Value.(type) {
			case float64:
				value = v
			case int64:
				value = float64(v)
			case uint64:
				value = float64(v)
			default:
				logger.Warn(
					"parquet history source: got unexpected value type",
					"type",
					reflect.TypeOf(keyValue.Value),
				)
				continue
			}

			existing.X = append(existing.X, currentStep)
			existing.Y = append(existing.Y, value)
			h.Metrics[keyValue.Key] = existing
		}
	}
	return h
}

// maxStepFromSummary extracts the "_step" value from the run summary.
// It returns unknownMaxStep if the summary doesn't contain "_step".
func maxStepFromSummary(runSummary map[string]any) int64 {
	switch n := runSummary["_step"].(type) {
	case float64:
		return int64(n)
	case int64:
		return n
	case uint64:
		return int64(n)
	default:
		return unknownMaxStep
	}
}

func getStepFromMetricsList(historySteps parquet.KeyValueList) (float64, error) {
	for _, historyStep := range historySteps {
		if historyStep.Key == parquet.StepKey {
			switch v := historyStep.Value.(type) {
			case float64:
				return v, nil
			case int64:
				return float64(v), nil
			case uint64:
				return float64(v), nil
			default:
				return -1.0, fmt.Errorf(
					"unexpected value type: %T",
					historyStep.Value,
				)
			}
		}
	}
	return -1.0, fmt.Errorf("step key not found")
}

// summaryMsg converts the run's summary from the backend to a SummaryMsg.
//
// Values that cannot be serialized are logged and skipped.
func (s *ParquetHistorySource) summaryMsg() SummaryMsg {
	summaryItems := make([]*spb.SummaryItem, 0, len(s.runInfo.runSummary))
	for key, value := range s.runInfo.runSummary {
		valueString, err := simplejsonext.MarshalToString(value)
		if err != nil {
			s.logger.Warn(
				"parquet history source: failed to serialize summary value",
				"key", key,
				"error", err,
			)
			continue
		}
		summaryItems = append(summaryItems, &spb.SummaryItem{
			Key:       key,
			ValueJson: valueString,
		})
	}

	return SummaryMsg{
		RunPath: s.runPath,
		Summary: []*spb.SummaryRecord{
			{
				Update: summaryItems,
			},
		},
	}
}

// loadRunInfo loads information about the run from the backend.
func loadRunInfo(
	ctx context.Context,
	graphqlClient graphql.Client,
	entity string,
	project string,
	runId string,
	logger *observability.CoreLogger,
) (*RunInfo, error) {
	response, err := gql.QueryRunInfo(
		ctx,
		graphqlClient,
		entity,
		project,
		runId,
	)
	if err != nil {
		return nil, err
	}

	if response == nil || response.Project == nil {
		return nil, fmt.Errorf("project %q not found for entity %q", project, entity)
	}
	run := response.Project.Run
	if run == nil {
		return nil, fmt.Errorf("run %q not found in %s/%s", runId, entity, project)
	}

	runInfo := newRunInfo(entity, project, &run.LeetRun, logger)
	if run.SummaryMetrics != "" {
		runInfo.runSummary, err = simplejsonext.UnmarshalObjectString(run.SummaryMetrics)
		if err != nil {
			return nil, err
		}
	}
	return runInfo, nil
}

// remoteRunState maps backend run states to the states rendered by LEET.
// Pending and unknown states remain Unknown because they do not establish
// either liveness or a terminal outcome for the local UI.
func remoteRunState(state string) RunState {
	switch strings.ToLower(state) {
	case "running", "preempting":
		return RunStateRunning
	case "finished":
		return RunStateFinished
	case "crashed":
		return RunStateCrashed
	case "failed", "killed", "preempted":
		return RunStateFailed
	default:
		return RunStateUnknown
	}
}
