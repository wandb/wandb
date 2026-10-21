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

// systemMetricsBatch is the result of one query for a run's system metrics.
type systemMetricsBatch struct {
	msgs []tea.Msg

	// last is the time of the latest sample in msgs, in seconds since the
	// Unix epoch.
	last float64
}

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

// loadSystemMetrics starts fetching the system metrics the run logged since
// the last batch, all of them at first, and returns the channel that
// delivers them as StatsMsgs, or nil when the run has none.
func (s *ParquetHistorySource) loadSystemMetrics() <-chan systemMetricsBatch {
	keys := s.runInfo.systemMetricKeys()
	if len(keys) == 0 || s.graphqlClient == nil {
		return nil
	}

	runInfo, since := s.runInfo, s.systemMetricsLast // Reads race with polls otherwise.
	ch := make(chan systemMetricsBatch, 1)
	go func() {
		batch, err := s.queryBucketedSystemMetrics(runInfo, keys, since)
		if err != nil {
			s.logger.Warn(
				"parquet history source: failed to load system metrics",
				"run", s.runPath,
				"error", err,
			)
		}
		ch <- batch
	}()
	return ch
}

// systemMetricsMsgs returns the system metrics once they have loaded,
// waiting for them if wait is set, and nothing on later calls.
func (s *ParquetHistorySource) systemMetricsMsgs(wait bool) []tea.Msg {
	if s.systemMetrics == nil {
		return nil
	}

	var batch systemMetricsBatch
	if wait {
		batch = <-s.systemMetrics
	} else {
		select {
		case batch = <-s.systemMetrics:
		default:
			return nil
		}
	}
	s.systemMetrics = nil
	s.systemMetricsLast = max(s.systemMetricsLast, batch.last)
	return batch.msgs
}

// queryBucketedSystemMetrics fetches the given system metrics logged after
// since, all of them when since is zero, averaged into time buckets, as
// one StatsMsg per bucket in time order.
//
// A single spec keeps the request under the backend's cap on system metric
// fetches per request, which it enforces by silently dropping specs.
func (s *ParquetHistorySource) queryBucketedSystemMetrics(
	runInfo *RunInfo,
	keys []string,
	since float64,
) (systemMetricsBatch, error) {
	spec := map[string]any{
		"keys":  keys,
		"bins":  remoteSystemMetricsBins,
		"xAxis": "_timestamp",
	}
	if since > 0 {
		// The bound is inclusive: the sample at since comes back as its own
		// bucket and is dropped below.
		spec["minX"] = since
	}
	specJSON, err := json.Marshal(spec)
	if err != nil {
		return systemMetricsBatch{}, err
	}

	response, err := gql.QueryRunBucketedHistory(
		s.ctx,
		s.graphqlClient,
		runInfo.entity,
		runInfo.project,
		runInfo.runId,
		[]string{string(specJSON)},
	)
	if err != nil {
		return systemMetricsBatch{}, err
	}
	if response == nil || response.Project == nil || response.Project.Run == nil {
		return systemMetricsBatch{}, errors.New("run not found")
	}

	var batch systemMetricsBatch
	for _, history := range response.Project.Run.BucketedHistory {
		buckets, _ := history.([]any)
		for _, bucket := range buckets {
			msg, last, ok := s.bucketStatsMsg(bucket)
			if !ok || last <= since {
				continue
			}
			batch.msgs = append(batch.msgs, msg)
			batch.last = max(batch.last, last)
		}
	}
	return batch, nil
}

// bucketStatsMsg converts a bucket, which holds "<key>Avg", "<key>Min" and
// similar aggregates for every key in the spec and for the x-axis, to a
// StatsMsg keyed like a local run's stats records, and returns the time of
// the bucket's last sample.
func (s *ParquetHistorySource) bucketStatsMsg(bucket any) (StatsMsg, float64, bool) {
	fields, _ := bucket.(map[string]any)
	timestamp, ok := fields["_timestampAvg"].(float64)
	if !ok {
		return StatsMsg{}, 0, false
	}
	last, ok := fields["_timestampLast"].(float64)
	if !ok {
		last = timestamp
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
		return StatsMsg{}, 0, false
	}

	return StatsMsg{
		RunPath:   s.runPath,
		Timestamp: int64(timestamp),
		Metrics:   metrics,
	}, last, true
}
