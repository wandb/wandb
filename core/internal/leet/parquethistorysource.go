package leet

import (
	"context"
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
) *ParquetHistorySource {
	ctx, cancel := context.WithCancel(ctx)

	return &ParquetHistorySource{
		logger:       logger,
		ctx:          ctx,
		cancel:       cancel,
		runPath:      fmt.Sprintf("%s/%s/%s", runInfo.entity, runInfo.project, runInfo.runId),
		maxKnownStep: maxStepFromSummary(runInfo.runSummary),
		runInfo:      runInfo,
		reader:       reader,
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
			BaseURL:            baseURL,
			RetryMax:           3,
			RetryWaitMin:       1 * time.Second,
			RetryWaitMax:       10 * time.Second,
			NonRetryTimeout:    10 * time.Second,
			CredentialProvider: credentialProvider,
			Logger:             logger.Logger,
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
			Source: newParquetHistorySource(ctx, runInfo, reader, logger),
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
		histories = append(histories, parseParquetHistorySteps(historySteps, s.logger))
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
