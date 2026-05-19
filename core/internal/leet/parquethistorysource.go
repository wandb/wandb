package leet

import (
	"context"
	"fmt"
	"io"
	"os"
	"reflect"
	"slices"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/Khan/genqlient/graphql"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/gql"
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
)

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

// NewRunInfo creates a new RunInfo.
//
// Exported for testing.
func NewRunInfo(
	entity string,
	project string,
	runId string,
	runSummary map[string]any,
	displayName string,
) *RunInfo {
	return &RunInfo{
		entity:      entity,
		project:     project,
		runId:       runId,
		runSummary:  runSummary,
		displayName: displayName,
	}
}

type ParquetHistorySource struct {
	logger *observability.CoreLogger

	// ctx is cancelled by Close to abort in-flight requests
	// and prevent reads after shutdown.
	ctx    context.Context
	cancel context.CancelFunc

	// readerDone is a flag to indicate if the reader is done.
	readerDone bool

	// runhistoryreader is the reader for the run history's parquet files.
	runhistoryreader *runhistoryreader.HistoryReader

	// runPath identifies the remote run in messages.
	runPath string

	// currentStep is the current step of the reader.
	currentStep int64

	// maxKnownStep is the last step logged by the run, extracted from the
	// run summary's "_step" field. Used as the termination bound: scanning
	// stops when currentStep exceeds this value. A negative value means the
	// summary did not provide a bound.
	maxKnownStep int64

	// runInfo is the information about the run.
	runInfo *RunInfo
}

// NewParquetHistorySource creates a new ParquetHistorySource.
func NewParquetHistorySource(
	ctx context.Context,
	entity string,
	project string,
	runId string,
	graphqlClient graphql.Client,
	httpClient api.RetryableClient,
	runInfo *RunInfo,
	logger *observability.CoreLogger,
	rustArrowWrapper *ffi.RustArrowWrapper,
) (*ParquetHistorySource, error) {
	ctx, cancel := context.WithCancel(ctx)

	historyReader, err := runhistoryreader.New(
		ctx,
		entity,
		project,
		runId,
		graphqlClient,
		httpClient,
		[]string{}, // keys
		false,      // useCache
		rustArrowWrapper,
	)
	if err != nil {
		cancel()
		return nil, err
	}

	return &ParquetHistorySource{
		logger:           logger,
		ctx:              ctx,
		cancel:           cancel,
		runPath:          remoteRunPath(entity, project, runId),
		currentStep:      0,
		maxKnownStep:     maxStepFromSummary(runInfo),
		runInfo:          runInfo,
		runhistoryreader: historyReader,
	}, nil
}

// InitializeParquetHistorySource returns a tea.Cmd that initializes a
// ParquetHistorySource for a remote run.
func InitializeParquetHistorySource(
	runParams *RemoteRunParams,
	logger *observability.CoreLogger,
) tea.Cmd {
	return func() tea.Msg {
		entity := runParams.Entity
		project := runParams.Project
		runId := runParams.RunId

		// Read the api key from the netrc file for the given base url.
		apiKey := os.Getenv("WANDB_API_KEY")
		if apiKey == "" {
			return ErrorMsg{Err: fmt.Errorf("WANDB_API_KEY is not set")}
		}

		settingsProto := &spb.Settings{
			ApiKey:  wrapperspb.String(apiKey),
			BaseUrl: wrapperspb.String(runParams.BaseURL),
		}
		s := settings.From(settingsProto)

		graphqlClient := initGraphQLClient(s, logger)
		httpClient := api.NewClient(api.ClientOptions{
			BaseURL:            stream.BaseURLFromSettings(logger, s),
			RetryMax:           3,
			RetryWaitMin:       1 * time.Second,
			RetryWaitMax:       10 * time.Second,
			NonRetryTimeout:    10 * time.Second,
			CredentialProvider: stream.CredentialsFromSettings(logger, s),
			Logger:             logger.Logger,
		})
		runInfo, err := loadRunInfo(
			graphqlClient,
			entity,
			project,
			runId,
		)
		if err != nil {
			return ErrorMsg{Err: err}
		}

		rustArrowWrapper, err := ffi.NewRustArrowWrapper()
		if err != nil {
			return ErrorMsg{Err: err}
		}

		source, err := NewParquetHistorySource(
			context.Background(),
			entity,
			project,
			runId,
			graphqlClient,
			httpClient,
			runInfo,
			logger,
			rustArrowWrapper,
		)
		if err != nil {
			return ErrorMsg{Err: err}
		}
		return InitMsg{
			Source: source,
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
		if s.runInfo != nil {
			msgs = append(msgs,
				RunMsg{
					RunPath:     s.runPath,
					ID:          s.runInfo.runId,
					Project:     s.runInfo.project,
					DisplayName: s.runInfo.displayName,
					Config:      nil,
				},
				s.processRunSummary(),
			)
		}
	}

	for time.Since(startTime) < maxTimePerChunk && numMsgs < chunkSize {
		if s.maxKnownStep >= 0 && s.currentStep > s.maxKnownStep {
			hasMore = false
			s.readerDone = true
			break
		}

		nextStep := s.currentStep + int64(parquetBatchScanSize)
		historySteps, err := s.runhistoryreader.GetHistorySteps(
			s.ctx,
			s.currentStep,
			nextStep,
		)
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
		historyMsg := ParseParquetHistorySteps(historySteps, s.logger)
		histories = append(histories, historyMsg)
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
		Progress: int(s.currentStep),
	}, nil
}

// Close implements HistorySource.Close.
func (s *ParquetHistorySource) Close() {
	s.cancel()
	s.runhistoryreader.Release()
}

// ParseParquetHistorySteps converts a list of iterator.KeyValueList to a HistoryMsg.
func ParseParquetHistorySteps(
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
			default:
				logger.Warn(
					"parquet history source: got unexpected value type",
					"type",
					reflect.TypeOf(keyValue.Value),
				)
				continue
			}

			h.Metrics[keyValue.Key] = MetricData{
				X: slices.Concat(existing.X, []float64{currentStep}),
				Y: slices.Concat(existing.Y, []float64{value}),
			}
		}
	}
	return h
}

// maxStepFromSummary extracts the "_step" value from the run summary.
// It returns unknownMaxStep if the summary is nil or doesn't contain "_step".
func maxStepFromSummary(runInfo *RunInfo) int64 {
	if runInfo == nil {
		return unknownMaxStep
	}
	v, ok := runInfo.runSummary["_step"]
	if !ok {
		return unknownMaxStep
	}
	switch n := v.(type) {
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

// processRunSummary converts the run's summary from the backend to a SummaryMsg.
func (s *ParquetHistorySource) processRunSummary() tea.Msg {
	summaryItems := make([]*spb.SummaryItem, 0)
	if s.runInfo != nil {
		for key, value := range s.runInfo.runSummary {
			valueString, err := simplejsonext.MarshalToString(value)
			if err != nil {
				return ErrorMsg{Err: err}
			}
			summaryItems = append(summaryItems, &spb.SummaryItem{
				Key:       key,
				ValueJson: valueString,
			})
		}
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

func initGraphQLClient(
	s *settings.Settings,
	logger *observability.CoreLogger,
) graphql.Client {
	baseURL := stream.BaseURLFromSettings(
		logger,
		s,
	)
	credentialProvider := stream.CredentialsFromSettings(
		logger,
		s,
	)

	return stream.NewGraphQLClient(
		baseURL,
		"", /*clientID*/
		credentialProvider,
		logger,
		&observability.Peeker{},
		s,
	)
}

// loadRunInfo loads information about the run from the backend.
func loadRunInfo(
	graphqlClient graphql.Client,
	entity string,
	project string,
	runId string,
) (*RunInfo, error) {
	response, err := gql.QueryRunInfo(
		context.Background(),
		graphqlClient,
		entity,
		project,
		runId,
	)
	if err != nil {
		return nil, err
	}

	if response == nil {
		return nil, fmt.Errorf("run %q not found in %s/%s", runId, entity, project)
	}
	if response.Project == nil {
		return nil, fmt.Errorf("project %q not found for entity %q", project, entity)
	}
	if response.Project.Run == nil {
		return nil, fmt.Errorf("run %q not found in %s/%s", runId, entity, project)
	}

	var displayName string
	if response.Project.Run.DisplayName != nil {
		displayName = *response.Project.Run.DisplayName
	}

	runSummaryString := response.Project.Run.SummaryMetrics
	var runSummaryJson map[string]any
	if runSummaryString != nil {
		runSummaryJson, err = simplejsonext.UnmarshalObjectString(*runSummaryString)
		if err != nil {
			return nil, err
		}
	}

	return &RunInfo{
		displayName: displayName,
		entity:      entity,
		project:     project,
		runId:       runId,
		runSummary:  runSummaryJson,
	}, nil
}

func remoteRunPath(entity, project, runId string) string {
	return fmt.Sprintf("%s/%s/%s", entity, project, runId)
}
