package leet

import (
	"context"
	"fmt"
	"io"
	"reflect"
	"slices"
	"strings"
	"time"

	"github.com/Khan/genqlient/graphql"
	tea "github.com/charmbracelet/bubbletea"

	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhistoryreader"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/iterator"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	parquetBatchScanSize = 100
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

	// readerDone is a flag to indicate if the reader is done.
	readerDone bool

	// runhistoryreader is the reader for the run history's parquet files.
	runhistoryreader *runhistoryreader.HistoryReader

	// currentStep is the current step of the reader.
	currentStep int64

	// runInfo is the information about the run.
	runInfo *RunInfo
}

// NewParquetHistorySource creates a new ParquetHistorySource for the given run path.
//
// A run path is a string in the format of "wandb://<entity>/<project>/<runId>".
func NewParquetHistorySource(
	entity string,
	project string,
	runId string,
	graphqlClient graphql.Client,
	httpClient api.RetryableClient,
	runInfo *RunInfo,
	logger *observability.CoreLogger,
) (*ParquetHistorySource, error) {
	historyReader, err := runhistoryreader.New(
		context.Background(),
		entity,
		project,
		runId,
		graphqlClient,
		httpClient,
		[]string{}, // keys
		false,      // useCache
	)
	if err != nil {
		return nil, err
	}

	return &ParquetHistorySource{
		logger:           logger,
		currentStep:      0,
		runInfo:          runInfo,
		runhistoryreader: historyReader,
	}, nil
}

// InitializeParquetHistorySource returns a tea.Cmd that initializes a
// ParquetHistorySource for the given run path.
//
// A run path is a string in the format of "wandb://<entity>/<project>/<runId>".
func InitializeParquetHistorySource(
	runPath string,
	logger *observability.CoreLogger,
) tea.Cmd {
	return func() tea.Msg {
		entity, project, runId := parseRemoteRunPath(runPath)

		s, err := settings.LoadSettings()
		if err != nil {
			return ErrorMsg{Err: err}
		}

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
			logger,
		)
		if err != nil {
			return ErrorMsg{Err: err}
		}

		source, err := NewParquetHistorySource(
			entity,
			project,
			runId,
			graphqlClient,
			httpClient,
			runInfo,
			logger,
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

	var msgs []tea.Msg
	var histories []HistoryMsg
	startTime := time.Now()
	hasMore := true
	numMsgs := 0

	if s.currentStep == 0 {
		if s.runInfo != nil {
			msgs = append(msgs,
				RunMsg{
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
		historySteps, err := s.runhistoryreader.GetHistorySteps(
			context.Background(),
			s.currentStep,
			s.currentStep+int64(parquetBatchScanSize),
		)
		if err != nil {
			return nil, err
		}

		s.currentStep += int64(len(historySteps))
		historyMsg := ParseParquetHistorySteps(historySteps, s.logger)
		histories = append(histories, historyMsg)
		numMsgs += len(historySteps)

		if len(historySteps) == 0 {
			hasMore = false
			s.readerDone = true
			break
		}
	}

	if len(histories) > 0 {
		msgs = append(msgs, concatenateHistory(histories))
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
	s.runhistoryreader.Release()
}

// ParseParquetHistorySteps converts a list of iterator.KeyValueList to a HistoryMsg.
func ParseParquetHistorySteps(
	historySteps []iterator.KeyValueList,
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
			if keyValue.Key == iterator.StepKey {
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

func getStepFromMetricsList(historySteps iterator.KeyValueList) (float64, error) {
	for _, historyStep := range historySteps {
		if historyStep.Key == iterator.StepKey {
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
		Summary: []*spb.SummaryRecord{
			{
				Update: summaryItems,
			},
		},
	}
}

// parseRemoteRunPath parses a run path into entity, project, and run id.
//
// A run path is a string in the format of "wandb://<entity>/<project>/<runId>".
// or alternatively in the format of "wandb://<entity>/<project>/runs/<runId>".
func parseRemoteRunPath(
	runPath string,
) (entity, project, runId string) {
	runPath = strings.TrimPrefix(runPath, "wandb://")

	runPath = strings.ReplaceAll(runPath, "/runs/", "/")
	runPath = strings.TrimPrefix(runPath, "/")

	parts := strings.Split(runPath, "/")
	if strings.Contains(parts[len(parts)-1], ":") {
		runId = strings.Split(parts[len(parts)-1], ":")[1]
		parts[len(parts)-1] = strings.Split(parts[len(parts)-1], ":")[0]
	} else if parts[len(parts)-1] != "" {
		runId = parts[len(parts)-1]
	}

	entity = parts[0]
	project = parts[1]

	return entity, project, runId
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
	logger *observability.CoreLogger,
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
	logger.Debug("run info", "response", response)

	displayName := response.Project.Run.DisplayName

	runSummaryString := response.Project.Run.SummaryMetrics
	var runSummaryJson map[string]any
	if runSummaryString != nil {
		runSummaryJson, err = simplejsonext.UnmarshalObjectString(*runSummaryString)
		if err != nil {
			return nil, err
		}
	}

	return &RunInfo{
		displayName: *displayName,
		entity:      entity,
		project:     project,
		runId:       runId,
		runSummary:  runSummaryJson,
	}, nil
}
