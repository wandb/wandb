package leet

import (
	"encoding/json"
	"errors"
	"slices"
	"strings"

	tea "charm.land/bubbletea/v2"

	"github.com/wandb/wandb/core/internal/gql"
)

// remoteSystemMetricsBins is the number of time buckets a remote run's
// system metrics are averaged into.
const remoteSystemMetricsBins = 500

// systemMetricKeys lists the run's numeric system metrics the way the W&B
// backend's history queries name them: "system/<name>" for a metric stored
// as "system.<name>".
func (ri *RunInfo) systemMetricKeys() []string {
	var keys []string
	for key, value := range ri.systemMetrics {
		name, ok := strings.CutPrefix(key, "system.")
		if !ok {
			continue
		}
		switch value.(type) {
		case float64, int64, uint64:
			keys = append(keys, "system/"+name)
		}
	}
	slices.Sort(keys)
	return keys
}

// loadSystemMetrics starts fetching the run's system metrics from the W&B
// backend and returns the channel that delivers them as StatsMsgs, or nil
// when the run has none.
func (s *ParquetHistorySource) loadSystemMetrics() <-chan []tea.Msg {
	keys := s.runInfo.systemMetricKeys()
	if len(keys) == 0 || s.graphqlClient == nil {
		return nil
	}

	runInfo := s.runInfo // Live runs replace s.runInfo on refresh.
	ch := make(chan []tea.Msg, 1)
	go func() {
		msgs, err := s.queryBucketedSystemMetrics(runInfo, keys)
		if err != nil {
			s.logger.Warn(
				"parquet history source: failed to load system metrics",
				"run", s.runPath,
				"error", err,
			)
		}
		ch <- msgs
	}()
	return ch
}

// systemMetricsMsgs returns the system metrics once they have loaded,
// waiting for them if wait is set, and nothing on later calls.
func (s *ParquetHistorySource) systemMetricsMsgs(wait bool) []tea.Msg {
	if s.systemMetrics == nil {
		return nil
	}
	if !wait {
		select {
		case msgs := <-s.systemMetrics:
			s.systemMetrics = nil
			return msgs
		default:
			return nil
		}
	}
	msgs := <-s.systemMetrics
	s.systemMetrics = nil
	return msgs
}

// queryBucketedSystemMetrics fetches the given system metrics averaged
// into time buckets, as one StatsMsg per bucket in time order.
//
// A single spec keeps the request under the backend's cap on system metric
// fetches per request, which it enforces by silently dropping specs.
func (s *ParquetHistorySource) queryBucketedSystemMetrics(
	runInfo *RunInfo,
	keys []string,
) ([]tea.Msg, error) {
	spec, err := json.Marshal(map[string]any{
		"keys":  keys,
		"bins":  remoteSystemMetricsBins,
		"xAxis": "_timestamp",
	})
	if err != nil {
		return nil, err
	}

	response, err := gql.QueryRunBucketedHistory(
		s.ctx,
		s.graphqlClient,
		runInfo.entity,
		runInfo.project,
		runInfo.runId,
		[]string{string(spec)},
	)
	if err != nil {
		return nil, err
	}
	if response == nil || response.Project == nil || response.Project.Run == nil {
		return nil, errors.New("run not found")
	}

	var msgs []tea.Msg
	for _, history := range response.Project.Run.BucketedHistory {
		buckets, _ := history.([]any)
		for _, bucket := range buckets {
			if msg, ok := s.bucketStatsMsg(bucket); ok {
				msgs = append(msgs, msg)
			}
		}
	}
	return msgs, nil
}

// bucketStatsMsg converts a bucket, which holds "<key>Avg", "<key>Min" and
// similar aggregates for every key in the spec and for the x-axis, to a
// StatsMsg keyed like a local run's stats records.
func (s *ParquetHistorySource) bucketStatsMsg(bucket any) (StatsMsg, bool) {
	fields, _ := bucket.(map[string]any)
	timestamp, ok := fields["_timestampAvg"].(float64)
	if !ok {
		return StatsMsg{}, false
	}

	metrics := make(map[string]float64)
	for field, value := range fields {
		name, ok := strings.CutPrefix(field, "system/")
		if !ok {
			continue
		}
		name, ok = strings.CutSuffix(name, "Avg")
		if !ok {
			continue
		}
		if v, ok := value.(float64); ok {
			metrics[name] = v
		}
	}
	if len(metrics) == 0 {
		return StatsMsg{}, false
	}

	return StatsMsg{
		RunPath:   s.runPath,
		Timestamp: int64(timestamp),
		Metrics:   metrics,
	}, true
}
