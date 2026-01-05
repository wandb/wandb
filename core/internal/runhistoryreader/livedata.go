package runhistoryreader

import (
	"context"
	"fmt"
	"log/slog"
	"math"

	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/iterator"
)

// GetLiveData gets live data from the W&B backend for a run
// which hasn't been written to parquet files yet.
func (h *HistoryReader) getLiveData(
	ctx context.Context,
	minStep int64,
	maxStep int64,
	selectAllKeys bool,
) ([]iterator.KeyValueList, error) {
	requireLiveDataQuery := minStep >= h.minLiveStep || maxStep >= h.minLiveStep
	if !requireLiveDataQuery {
		return []iterator.KeyValueList{}, nil
	}

	if selectAllKeys {
		results, err := h.getLiveDataForAllKeys(
			ctx,
			minStep,
			maxStep,
		)
		if err != nil {
			return nil, err
		}

		return results, nil
	} else {
		results, err := h.getLiveDataForSpecificKeys(
			ctx,
			minStep,
			maxStep,
		)
		if err != nil {
			return nil, err
		}
		return results, nil
	}
}

func (h *HistoryReader) getLiveDataForAllKeys(
	ctx context.Context,
	minStep int64,
	maxStep int64,
) ([]iterator.KeyValueList, error) {
	pageSize := maxStep - minStep
	response, err := gql.HistoryPage(
		ctx,
		h.graphqlClient,
		h.entity,
		h.project,
		h.runId,
		minStep,
		maxStep,
		int(pageSize),
	)
	if err != nil {
		return nil, err
	}

	if response.GetProject() == nil || response.GetProject().GetRun() == nil {
		return nil, fmt.Errorf("no history found for run %s", h.runId)
	}

	history := response.GetProject().GetRun().GetHistory()
	results := make([]iterator.KeyValueList, 0, len(history))
	for _, historyRow := range history {
		historyRowObject, err := simplejsonext.UnmarshalObjectString(historyRow)
		if err != nil {
			return nil, err
		}
		results = append(results, convertHistoryRowToKeyValueList(historyRowObject))
	}

	return results, nil
}

func (h *HistoryReader) getLiveDataForSpecificKeys(
	ctx context.Context,
	minStep int64,
	maxStep int64,
) ([]iterator.KeyValueList, error) {
	h.keys = append(h.keys, iterator.StepKey)

	spec := map[string]any{
		"keys":    h.keys,
		"minStep": minStep,
		"maxStep": maxStep,
		"samples": maxStep - minStep,
	}
	specJSON, err := simplejsonext.MarshalToString(spec)
	if err != nil {
		slog.Error("failed to marshal spec", "error", err)
		return nil, err
	}

	response, err := gql.SampledHistoryPage(
		ctx,
		h.graphqlClient,
		h.entity,
		h.project,
		h.runId,
		specJSON,
	)
	if err != nil {
		slog.Error("failed to get sampled history page", "error", err)
		return nil, err
	}

	slog.Info("sampled history response", "response", response)

	if response.GetProject() == nil || response.GetProject().GetRun() == nil {
		return nil, fmt.Errorf("no history found for run %s", h.runId)
	}

	results := make(
		[]iterator.KeyValueList,
		0,
		len(response.GetProject().GetRun().GetSampledHistory()),
	)
	for _, sampledHistory := range response.GetProject().GetRun().GetSampledHistory() {
		sampledHistoryList, ok := sampledHistory.([]any)
		if !ok {
			return nil, fmt.Errorf(
				"failed to parse history: unexpected type %T",
				sampledHistory,
			)
		}

		for _, sampledHistoryItem := range sampledHistoryList {
			sampledHistoryItemMap, ok := sampledHistoryItem.(map[string]any)
			if !ok {
				return nil, fmt.Errorf(
					"failed to parse history item: unexpected type %T",
					sampledHistoryItem,
				)
			}
			results = append(
				results,
				convertHistoryRowToKeyValueList(sampledHistoryItemMap),
			)
		}
	}

	return results, nil
}

func convertHistoryRowToKeyValueList(
	historyRowObject map[string]any,
) iterator.KeyValueList {
	kvList := make(iterator.KeyValueList, 0, len(historyRowObject))
	for key, value := range historyRowObject {
		val := value

		// In some cases the backend returns the step as a float64,
		// so we need to convert it to an int64.
		if key == iterator.StepKey {
			if valAsFloat, ok := val.(float64); ok {
				val = int64(valAsFloat)
			}
		}
		kvList = append(kvList, iterator.KeyValuePair{Key: key, Value: val})
	}
	return kvList
}

// getMinLiveStep gets the minimum step present from the live data.
func getMinLiveStep(liveSteps []float64) (int64, error) {
	minLiveStep := math.MaxFloat64
	for _, stepValue := range liveSteps {
		if stepValue < minLiveStep {
			minLiveStep = stepValue
		}
	}

	return int64(minLiveStep), nil
}
