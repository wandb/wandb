package leet

import (
	"encoding/json"
	"fmt"
	"slices"
	"strings"

	tea "charm.land/bubbletea/v2"
	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/gql"
)

const remoteMetricsBins = 500

// loadRemoteSystemMetrics fetches bucketed system-metric history.
func (s *ParquetHistorySource) loadRemoteSystemMetrics() ([]tea.Msg, error) {
	// Find all system metrics we want to fetch from the backend.
	metricKeys, err := s.loadRemoteSystemMetricKeys()
	if err != nil {
		return nil, err
	}
	if len(metricKeys) == 0 {
		return nil, nil
	}

	specs := make([]string, 0, len(metricKeys))
	for _, key := range metricKeys {
		spec, err := simplejsonext.MarshalToString(map[string]any{
			"keys":  []string{key},
			"bins":  remoteMetricsBins,
			"xAxis": "_timestamp",
		})
		if err != nil {
			return nil, fmt.Errorf(
				"marshal bucketed system metric spec for %s: %w", key, err,
			)
		}
		specs = append(specs, spec)
	}

	// Query the backend for system metrics.
	response, err := gql.QueryRunBucketedHistory(
		s.ctx,
		s.graphqlClient,
		s.runInfo.entity,
		s.runInfo.project,
		s.runInfo.runId,
		specs,
	)
	if err != nil {
		return nil, fmt.Errorf("query remote bucketed system metrics: %w", err)
	}
	if response == nil || response.Project == nil || response.Project.Run == nil {
		return nil, fmt.Errorf("remote bucketed system metrics returned no run")
	}

	// Extract bucketed system metrics by timestamp.
	metricsByTimestamp := make(map[int64]map[string]float64)
	timestamps := make([]int64, 0)
	for _, rawHistory := range response.Project.Run.BucketedHistory {
		buckets, err := decodeBucketedHistory(rawHistory)
		if err != nil {
			return nil, fmt.Errorf("parse bucketed system metrics: %w", err)
		}

		for _, rawBucket := range buckets {
			bucket, ok := rawBucket.(map[string]any)
			if !ok {
				continue
			}

			timestamp, ok := bucketMetricValue(bucket, "_timestamp")
			if !ok {
				continue
			}

			timestampKey := int64(timestamp)
			metrics := metricsByTimestamp[timestampKey]
			if metrics == nil {
				metrics = make(map[string]float64)
				metricsByTimestamp[timestampKey] = metrics
				timestamps = append(timestamps, timestampKey)
			}

			for key, rawValue := range bucket {
				if !strings.HasSuffix(key, "Avg") {
					continue
				}

				metricKey := strings.TrimSuffix(key, "Avg")
				if !strings.HasPrefix(metricKey, "system.") &&
					!strings.HasPrefix(metricKey, "system/") {
					continue
				}

				if value, ok := valueToFloat(rawValue); ok {
					metrics[normalizeRemoteSystemMetricKey(metricKey)] = value
				}
			}
		}
	}

	slices.Sort(timestamps)

	metrics := make([]tea.Msg, 0, len(timestamps))
	for _, timestamp := range timestamps {
		metrics = append(metrics, StatsMsg{
			RunPath:   s.runPath,
			Timestamp: timestamp,
			Metrics:   metricsByTimestamp[timestamp],
		})
	}

	return metrics, nil
}

func (s *ParquetHistorySource) loadRemoteSystemMetricKeys() ([]string, error) {
	response, err := gql.QueryRunHistoryKeys(
		s.ctx,
		s.graphqlClient,
		s.runInfo.entity,
		s.runInfo.project,
		s.runInfo.runId,
	)
	if err != nil {
		return nil, fmt.Errorf("query remote history keys: %w", err)
	}
	if response == nil || response.Project == nil || response.Project.Run == nil {
		return nil, fmt.Errorf("remote history keys returned no run")
	}
	if response.Project.Run.HistoryKeys == nil {
		return nil, nil
	}

	return parseRemoteSystemMetricKeys(*response.Project.Run.HistoryKeys)
}

func parseRemoteSystemMetricKeys(historyKeys any) ([]string, error) {
	root, ok := historyKeys.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("unexpected history keys type %T", historyKeys)
	}

	rawKeys, ok := root["keys"].(map[string]any)
	if !ok {
		return nil, nil
	}

	keys := make([]string, 0)
	for key, rawInfo := range rawKeys {
		if !isRemoteSystemMetricKey(key) {
			continue
		}

		info, ok := rawInfo.(map[string]any)
		if !ok || !isNumericHistoryKey(info) {
			continue
		}

		keys = append(keys, remoteSystemMetricBucketKey(key))
	}

	slices.Sort(keys)
	return slices.Compact(keys), nil
}

func isRemoteSystemMetricKey(key string) bool {
	return strings.HasPrefix(key, "system/") || strings.HasPrefix(key, "system.")
}

func remoteSystemMetricBucketKey(key string) string {
	if strings.HasPrefix(key, "system.") {
		return "system/" + strings.TrimPrefix(key, "system.")
	}
	return key
}

func isNumericHistoryKey(info map[string]any) bool {
	typeCounts, ok := info["typeCounts"].([]any)
	if !ok {
		return false
	}

	for _, raw := range typeCounts {
		entry, ok := raw.(map[string]any)
		if !ok {
			continue
		}

		typeName, _ := entry["type"].(string)
		if typeName == "number" {
			return true
		}
	}

	return false
}

func decodeBucketedHistory(value any) ([]any, error) {
	switch raw := value.(type) {
	case []any:
		return raw, nil
	case string:
		var decoded []any
		if err := json.Unmarshal([]byte(raw), &decoded); err != nil {
			return nil, fmt.Errorf("decode JSON result: %w", err)
		}
		return decoded, nil
	case json.RawMessage:
		var decoded []any
		if err := json.Unmarshal(raw, &decoded); err != nil {
			return nil, fmt.Errorf("decode JSON result: %w", err)
		}
		return decoded, nil
	default:
		return nil, fmt.Errorf("unexpected result type %T", value)
	}
}

func bucketMetricValue(bucket map[string]any, key string) (float64, bool) {
	// bucketedHistory returns aggregated fields (e.g. _timestampAvg).
	// Try searching for Avg value first, then use Last value as a fallback.
	for _, suffix := range []string{"Avg", "Last"} {
		if value, ok := valueToFloat(bucket[key+suffix]); ok {
			return value, true
		}
	}

	return 0, false
}

func normalizeRemoteSystemMetricKey(key string) string {
	key = strings.TrimPrefix(strings.TrimPrefix(key, "system."), "system/")
	if key == "memory" {
		return "memory_percent"
	}
	return key
}

func valueToFloat(value any) (float64, bool) {
	switch v := value.(type) {
	case float64:
		return v, true
	case int64:
		return float64(v), true
	case uint64:
		return float64(v), true
	case json.Number:
		value, err := v.Float64()
		return value, err == nil
	default:
		return 0, false
	}
}
