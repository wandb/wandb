package wbapi

import (
	"cmp"
	"context"
	"os"
	"sync"
	"time"

	lru "github.com/hashicorp/golang-lru"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runreader"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// maxOpenRuns bounds the runs kept open between requests.
const maxOpenRuns = 32

// LocalRunHandler serves runs from their transaction logs in a local wandb
// directory, without a W&B server.
type LocalRunHandler struct {
	logger *observability.CoreLogger

	// mu serializes access to runs, which are not safe for concurrent use.
	mu sync.Mutex

	// runs are the most recently read runs, kept open so that a later
	// request for the same run reads only what was appended since.
	runs *lru.Cache
}

func NewLocalRunHandler(logger *observability.CoreLogger) *LocalRunHandler {
	runs, _ := lru.NewWithEvict(maxOpenRuns, func(_, run any) {
		run.(*runreader.Run).Close()
	})
	return &LocalRunHandler{logger: logger, runs: runs}
}

// HandleListLocalRuns lists the runs in a wandb directory, newest first.
//
// Each run is probed rather than read in full, so this stays cheap for
// directories with many long runs.
func (h *LocalRunHandler) HandleListLocalRuns(
	ctx context.Context,
	request *spb.ListLocalRunsRequest,
) *spb.ApiResponse {
	dirs, err := runreader.ListRunDirs(request.GetWandbDir())
	if err != nil {
		return apiErrorResponse(err.Error(), 0)
	}

	response := &spb.ListLocalRunsResponse{}
	for _, dir := range dirs {
		if err := ctx.Err(); err != nil {
			return apiErrorResponse(err.Error(), 0)
		}
		probe, err := runreader.Probe(dir.WandbFile, h.logger)
		if err != nil {
			h.logger.Debug("wbapi: skipping local run", "path", dir.WandbFile, "error", err)
			continue
		}
		response.Runs = append(response.Runs,
			localRunInfo(dir.WandbFile, &probe.Info, probe.State))
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ListLocalRunsResponse{
			ListLocalRunsResponse: response,
		},
	}
}

// HandleReadLocalRun reads a run's identity, config, summary and state.
func (h *LocalRunHandler) HandleReadLocalRun(
	ctx context.Context,
	request *spb.ReadLocalRunRequest,
) *spb.ApiResponse {
	return h.withRun(ctx, request.GetWandbFile(), func(run *runreader.Run) *spb.ApiResponse {
		configJSON, err := run.ConfigJSON()
		if err != nil {
			return apiErrorResponse(err.Error(), 0)
		}
		summaryJSON, err := run.SummaryJSON()
		if err != nil {
			return apiErrorResponse(err.Error(), 0)
		}
		environmentJSON, err := run.EnvironmentJSON()
		if err != nil {
			return apiErrorResponse(err.Error(), 0)
		}

		info := run.Info()
		response := &spb.ReadLocalRunResponse{
			Info:            localRunInfo(request.GetWandbFile(), &info, run.State()),
			ConfigJson:      string(configJSON),
			SummaryJson:     string(summaryJSON),
			EnvironmentJson: string(environmentJSON),
			LastStep:        run.LastStep(),
			HistoryKeys:     run.HistoryKeys(),
		}
		if code, ok := run.ExitCode(); ok {
			response.ExitCode = &code
		}
		return &spb.ApiResponse{
			Response: &spb.ApiResponse_ReadLocalRunResponse{ReadLocalRunResponse: response},
		}
	})
}

// HandleReadLocalRunHistory reads the history rows matching the request.
func (h *LocalRunHandler) HandleReadLocalRunHistory(
	ctx context.Context,
	request *spb.ReadLocalRunHistoryRequest,
) *spb.ApiResponse {
	if request.Last != nil && request.GetLast() <= 0 {
		return apiErrorResponse("'last' must be positive", 0)
	}

	rows, err := runreader.ScanHistory(ctx, request.GetWandbFile(), runreader.HistoryQuery{
		Keys:    request.GetKeys(),
		MinStep: request.MinStep,
		MaxStep: request.MaxStep,
		Last:    int(request.GetLast()),
	}, h.logger)
	if err != nil {
		return apiErrorResponse(err.Error(), 0)
	}

	response := &spb.ReadLocalRunHistoryResponse{}
	for _, row := range rows {
		items := make([]*spb.LocalHistoryItem, 0, len(row.Items))
		for _, item := range row.Items {
			items = append(items, &spb.LocalHistoryItem{Key: item.Key, ValueJson: item.ValueJSON})
		}
		response.Rows = append(response.Rows, &spb.LocalHistoryRow{Step: row.Step, Items: items})
	}
	return &spb.ApiResponse{
		Response: &spb.ApiResponse_ReadLocalRunHistoryResponse{
			ReadLocalRunHistoryResponse: response,
		},
	}
}

// HandleReadLocalRunConsoleLogs reads a run's console output or its tail.
func (h *LocalRunHandler) HandleReadLocalRunConsoleLogs(
	ctx context.Context,
	request *spb.ReadLocalRunConsoleLogsRequest,
) *spb.ApiResponse {
	if request.Last != nil && request.GetLast() <= 0 {
		return apiErrorResponse("'last' must be positive", 0)
	}

	return h.withRun(ctx, request.GetWandbFile(), func(run *runreader.Run) *spb.ApiResponse {
		lines := run.Console()
		start := 0
		if request.Last != nil {
			start = max(len(lines)-int(request.GetLast()), 0)
		}

		response := &spb.ReadLocalRunConsoleLogsResponse{TotalLines: int64(len(lines))}
		for i := start; i < len(lines); i++ {
			response.Lines = append(response.Lines, consoleLogLine(int64(i), lines[i]))
		}
		return &spb.ApiResponse{
			Response: &spb.ApiResponse_ReadLocalRunConsoleLogsResponse{
				ReadLocalRunConsoleLogsResponse: response,
			},
		}
	})
}

// Close releases the runs kept open.
func (h *LocalRunHandler) Close() {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.runs.Purge()
}

// withRun opens the run at path or reuses it, brings it up to date, and
// calls fn while holding the handler's lock.
func (h *LocalRunHandler) withRun(
	ctx context.Context,
	path string,
	fn func(*runreader.Run) *spb.ApiResponse,
) *spb.ApiResponse {
	h.mu.Lock()
	defer h.mu.Unlock()

	run, err := h.open(path)
	if err != nil {
		return apiErrorResponse(err.Error(), 0)
	}
	if err := run.Update(ctx); err != nil {
		if ctx.Err() == nil {
			h.runs.Remove(path)
		}
		return apiErrorResponse(err.Error(), 0)
	}
	return fn(run)
}

// open returns the run cached at path, or opens it. A cached run whose file
// is gone is dropped, so a deleted run fails like a missing one.
func (h *LocalRunHandler) open(path string) (*runreader.Run, error) {
	if cached, ok := h.runs.Get(path); ok {
		if _, err := os.Stat(path); err == nil {
			return cached.(*runreader.Run), nil
		}
		h.runs.Remove(path)
	}
	run, err := runreader.Open(path, h.logger)
	if err != nil {
		return nil, err
	}
	h.runs.Add(path, run)
	return run, nil
}

func localRunInfo(
	wandbFile string,
	info *runreader.Info,
	state runreader.State,
) *spb.LocalRunInfo {
	dir := runreader.ParseRunDir(wandbFile)
	result := &spb.LocalRunInfo{
		WandbFile:   wandbFile,
		RunId:       cmp.Or(info.RunID, dir.RunID),
		Entity:      info.Entity,
		Project:     info.Project,
		DisplayName: info.DisplayName,
		Notes:       info.Notes,
		Tags:        info.Tags,
		Group:       info.Group,
		JobType:     info.JobType,
		SweepId:     info.SweepID,
		Host:        info.Host,
		Offline:     dir.Offline,
		State:       string(state),
	}
	if !info.StartTime.IsZero() {
		result.StartTime = timestamppb.New(info.StartTime)
	}
	return result
}

func consoleLogLine(number int64, line runreader.ConsoleLine) *spb.RunConsoleLogLine {
	result := &spb.RunConsoleLogLine{Number: number, Content: line.Content}
	if !line.Time.IsZero() {
		result.Timestamp = line.Time.UTC().Format(time.RFC3339Nano)
	}
	if line.Stderr {
		result.Level = "error"
	}
	return result
}
