package leet

import (
	"context"
	"fmt"
	"io"
	"math"
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
	"github.com/wandb/wandb/core/internal/runmetric"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	parquetBatchScanSize = 100
	unknownMaxStep       = -1
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
}

// historyStepReader pages through a remote run's exported history.
//
// Implemented by *runhistoryreader.HistoryReader.
type historyStepReader interface {
	GetHistorySteps(ctx context.Context, minStep, maxStep int64) ([]parquet.KeyValueList, error)
	Release()
}

// ParquetHistorySource reads a remote run's history from its parquet
// exports on the W&B backend.
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

	// reader is the reader for the run history's parquet files.
	reader historyStepReader

	// runPath identifies the remote run in messages.
	runPath string

	// currentStep is the current step of the reader.
	currentStep int64

	// maxKnownStep is the last step logged by the run, extracted from the
	// run summary's "_step" field. Used as the termination bound: scanning
	// stops when currentStep exceeds this value. A negative value means the
	// summary did not provide a bound.
	maxKnownStep int64

	// metricHandler contains the remote run's persisted metric definitions.
	metricHandler *runmetric.MetricHandler

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
	logger *observability.CoreLogger,
	metricHandler *runmetric.MetricHandler,
) *ParquetHistorySource {
	ctx, cancel := context.WithCancel(ctx)
	if metricHandler == nil {
		metricHandler = runmetric.New()
	}

	return &ParquetHistorySource{
		logger:        logger,
		ctx:           ctx,
		cancel:        cancel,
		runPath:       fmt.Sprintf("%s/%s/%s", runInfo.entity, runInfo.project, runInfo.runId),
		maxKnownStep:  maxStepFromSummary(runInfo.runSummary),
		metricHandler: metricHandler,
		runInfo:       runInfo,
		reader:        reader,
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
		// Read the API key passed by the Python wrapper.
		apiKey := os.Getenv("WANDB_API_KEY")
		if apiKey == "" {
			return ErrorMsg{Err: fmt.Errorf("WANDB_API_KEY is not set")}
		}

		s := settings.From(&spb.Settings{
			ApiKey:  wrapperspb.String(apiKey),
			BaseUrl: wrapperspb.String(runParams.BaseURL),
		})
		baseURL := stream.BaseURLFromSettings(logger, s)
		credentialProvider := stream.CredentialsFromSettings(logger, s)

		graphqlClient := stream.NewGraphQLClient(
			baseURL,
			"", /*clientID*/
			credentialProvider,
			logger,
			&observability.Peeker{},
			s,
		)
		httpClient := api.NewClient(api.ClientOptions{
			RetryMax:        3,
			RetryWaitMin:    1 * time.Second,
			RetryWaitMax:    10 * time.Second,
			NonRetryTimeout: 10 * time.Second,
			Logger:          logger.Logger,
			PreRetryLayers:  httplayers.LimitTo(baseURL, credentialProvider),
		})

		runInfo, err := loadRunInfo(
			ctx,
			graphqlClient,
			runParams.Entity,
			runParams.Project,
			runParams.RunID,
		)
		if err != nil {
			return ErrorMsg{Err: err}
		}

		metricHandler := loadWandbConfigMetrics(
			ctx,
			graphqlClient,
			runParams.Entity,
			runParams.Project,
			runParams.RunID,
			logger,
		)

		rustArrowWrapper, err := ffi.NewRustArrowWrapper()
		if err != nil {
			return ErrorMsg{Err: err}
		}

		reader, err := runhistoryreader.New(
			ctx,
			runInfo.entity,
			runInfo.project,
			runInfo.runId,
			graphqlClient,
			httpClient,
			[]string{}, // keys
			false,      // useCache
			rustArrowWrapper,
		)
		if err != nil {
			return ErrorMsg{Err: err}
		}

		return InitMsg{
			Source: newParquetHistorySource(
				ctx,
				runInfo,
				reader,
				logger,
				metricHandler,
			),
		}
	}
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

	var msgs []tea.Msg
	var histories []HistoryMsg
	startTime := time.Now()
	hasMore := true
	numMsgs := 0

	if s.currentStep == 0 {
		msgs = append(msgs,
			RunMsg{
				RunPath:     s.runPath,
				ID:          s.runInfo.runId,
				Entity:      s.runInfo.entity,
				Project:     s.runInfo.project,
				DisplayName: s.runInfo.displayName,
				Config:      nil,
			},
			s.summaryMsg(),
		)
	}

	for time.Since(startTime) < maxTimePerChunk && numMsgs < chunkSize {
		if s.maxKnownStep >= 0 && s.currentStep > s.maxKnownStep {
			hasMore = false
			s.readerDone = true
			break
		}

		nextStep := s.currentStep + int64(parquetBatchScanSize)
		historySteps, err := s.reader.GetHistorySteps(s.ctx, s.currentStep, nextStep)
		if err != nil {
			return nil, err
		}

		if len(historySteps) == 0 {
			if s.maxKnownStep < 0 {
				hasMore = false
				s.readerDone = true
				break
			}
			s.currentStep = nextStep
			continue
		}

		maxStep := historySteps[len(historySteps)-1].StepValue()
		if maxStep < s.currentStep {
			s.currentStep = nextStep
		} else {
			s.currentStep = maxStep + 1
		}
		histories = append(
			histories,
			parseParquetHistorySteps(historySteps, s.logger, s.metricHandler),
		)
		numMsgs += len(historySteps)

		if s.maxKnownStep >= 0 && s.currentStep > s.maxKnownStep {
			hasMore = false
			s.readerDone = true
			break
		}
	}

	if len(histories) > 0 {
		msgs = append(msgs, concatenateHistory(histories, s.runPath))
	}

	if !hasMore {
		msgs = append(msgs, FileCompleteMsg{ExitCode: 0})
	}

	return ChunkedBatchMsg{
		Msgs:     msgs,
		HasMore:  hasMore,
		Progress: numMsgs,
	}, nil
}

// Close implements HistorySource.Close.
func (s *ParquetHistorySource) Close() {
	s.close.Do(func() {
		s.cancel()
		s.reader.Release()
	})
}

// parseParquetHistorySteps converts a list of parquet.KeyValueList to a HistoryMsg.
func parseParquetHistorySteps(
	historySteps []parquet.KeyValueList,
	logger *observability.CoreLogger,
	metricHandler *runmetric.MetricHandler,
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

		// Collect the whole row before resolving axes, since a custom step
		// metric may appear later in the row than the metric that uses it.
		values := make(map[string]float64)
		for _, keyValue := range historyStep {
			if keyValue.Key == parquet.StepKey {
				continue
			}

			var value float64
			switch v := keyValue.Value.(type) {
			case float64:
				value = v
			case int64:
				value = float64(v)
			case uint64:
				value = float64(v)
			default:
				if !strings.HasPrefix(keyValue.Key, "_") {
					logger.Warn(
						"parquet history source: got unexpected value type",
						"type",
						reflect.TypeOf(keyValue.Value),
					)
				}
				continue
			}
			values[keyValue.Key] = value
		}

		for key, value := range values {
			if strings.HasPrefix(key, "_") {
				continue
			}

			xAxisMetric := metricHandler.StepMetric(key)
			if metricHandler.IsHidden(key) {
				continue
			}

			x := currentStep
			switch xAxisMetric {
			case "", parquet.StepKey:
				xAxisMetric = ""
			default:
				customStep, ok := values[xAxisMetric]
				if !ok || !isFinite(customStep) {
					continue
				}
				x = customStep
			}

			existing := h.Metrics[key]
			if existing.XAxisMetric != xAxisMetric {
				if existing.XAxisMetric != "" {
					continue
				}
				existing = MetricData{XAxisMetric: xAxisMetric}
			}
			existing.X = append(existing.X, x)
			existing.Y = append(existing.Y, value)
			h.Metrics[key] = existing
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

// decodeWandbConfigMetrics decodes persisted metric definitions from the
// run's private wandb config. The config uses numeric protobuf field names:
// 1 is name, 2 is glob_name, 4 is step_metric, 5 is a one-based index
// into the metric list for step_metric, and 6 contains metric options.
//
// Invalid definitions are ignored so remote runs retain the default _step
// axis, matching the local history reader's best-effort processing.
func decodeWandbConfigMetrics(wandbConfigJSON string) *runmetric.MetricHandler {
	handler := runmetric.New()
	config, err := simplejsonext.UnmarshalObjectString(wandbConfigJSON)
	if err != nil {
		return handler
	}

	rawMetrics, ok := config["m"].([]any)
	if !ok {
		return handler
	}

	// Decode all metrics into records.
	records := make([]*spb.MetricRecord, len(rawMetrics))
	for i, rawMetric := range rawMetrics {
		fields, ok := rawMetric.(map[string]any)
		if !ok {
			continue
		}

		record, ok := decodeWandbMetricRecord(fields)
		if !ok {
			continue
		}
		records[i] = record
	}

	// Resolve references after every record is available, then register
	// the completed definitions with the same handler used for local runs.
	for i, rawMetric := range rawMetrics {
		record := records[i]
		if record == nil {
			continue
		}

		fields, ok := rawMetric.(map[string]any)
		if !ok {
			continue
		}

		if rawIndex, exists := fields["5"]; exists {
			index, ok := persistedMetricIndex(rawIndex, len(records))
			if !ok || records[index-1] == nil {
				continue
			}
			switch {
			case records[index-1].Name != "":
				record.StepMetric = records[index-1].Name
			case records[index-1].GlobName != "":
				record.StepMetric = records[index-1].GlobName
			default:
				continue
			}
		}

		_ = handler.ProcessRecord(record)
	}

	return handler
}

// decodeWandbMetricRecord decodes the fields needed to resolve a metric's
// custom x-axis. It returns false for malformed entries or entries that
// incorrectly specify both an explicit name and a glob name.
func decodeWandbMetricRecord(
	fields map[string]any,
) (*spb.MetricRecord, bool) {
	record := &spb.MetricRecord{}

	if rawName, exists := fields["1"]; exists {
		name, ok := rawName.(string)
		if !ok {
			return nil, false
		}
		record.Name = name
	}

	if rawGlobName, exists := fields["2"]; exists {
		globName, ok := rawGlobName.(string)
		if !ok {
			return nil, false
		}
		record.GlobName = globName
	}

	if record.Name != "" && record.GlobName != "" {
		return nil, false
	}

	if rawStepMetric, exists := fields["4"]; exists {
		stepMetric, ok := rawStepMetric.(string)
		if !ok {
			return nil, false
		}
		record.StepMetric = stepMetric
	}

	if rawOptions, exists := fields["6"]; exists {
		options, ok := rawOptions.([]any)
		if !ok {
			return nil, false
		}
		for _, rawOption := range options {
			var option float64
			switch rawOption := rawOption.(type) {
			case int64:
				option = float64(rawOption)
			// Defensive check if JSON deserialization ever converts to float64.
			case float64:
				option = rawOption
			default:
				continue
			}

			if option == 2 {
				record.Options = &spb.MetricOptions{Hidden: true}
				break
			}
		}
	}

	return record, true
}

// persistedMetricIndex converts a JSON number into a valid one-based index
// into a persisted metric list.
func persistedMetricIndex(value any, metricCount int) (int, bool) {
	var index int64
	switch value := value.(type) {
	case int:
		index = int64(value)
	case int64:
		index = value
	case uint64:
		if value > math.MaxInt64 {
			return 0, false
		}
		index = int64(value)
	case float64:
		if value != math.Trunc(value) || value > math.MaxInt64 {
			return 0, false
		}
		index = int64(value)
	default:
		return 0, false
	}

	if index < 1 || index > int64(metricCount) {
		return 0, false
	}
	return int(index), true
}

// loadWandbConfigMetrics loads persisted metric definitions for a remote run.
//
// Metric metadata is optional for remote history rendering. If the config
// query fails or returns an unusable response, return an empty handler so
// callers retain the default _step behavior.
func loadWandbConfigMetrics(
	ctx context.Context,
	graphqlClient graphql.Client,
	entity string,
	project string,
	runId string,
	logger *observability.CoreLogger,
) *runmetric.MetricHandler {
	handler := runmetric.New()
	response, err := gql.QueryRunWandbConfig(
		ctx,
		graphqlClient,
		entity,
		project,
		runId,
	)
	if err != nil {
		logger.Warn(
			"parquet history source: failed to load metric definitions",
			"error", err,
		)
		return handler
	}

	if response == nil || response.Project == nil || response.Project.Run == nil {
		logger.Warn(
			"parquet history source: metric definition response missing run",
		)
		return handler
	}

	configJSON := response.Project.Run.WandbConfig
	if configJSON == nil {
		return handler
	}
	return decodeWandbConfigMetrics(*configJSON)
}

// loadRunInfo loads information about the run from the backend.
func loadRunInfo(
	ctx context.Context,
	graphqlClient graphql.Client,
	entity string,
	project string,
	runId string,
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
	if response.Project.Run == nil {
		return nil, fmt.Errorf("run %q not found in %s/%s", runId, entity, project)
	}

	var displayName string
	if response.Project.Run.DisplayName != nil {
		displayName = *response.Project.Run.DisplayName
	}

	var runSummary map[string]any
	if summaryJSON := response.Project.Run.SummaryMetrics; summaryJSON != nil {
		runSummary, err = simplejsonext.UnmarshalObjectString(*summaryJSON)
		if err != nil {
			return nil, err
		}
	}

	return &RunInfo{
		displayName: displayName,
		entity:      entity,
		project:     project,
		runId:       runId,
		runSummary:  runSummary,
	}, nil
}
