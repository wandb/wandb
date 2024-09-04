package monitor

import (
	"crypto/md5"
	"encoding/hex"
	"fmt"
	"regexp"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"

	"github.com/prometheus/common/expfmt"
)

type FilterValue interface {
	isOpenMetricsFilters_Value()
}

// OpenMetrics is a monitor that collects metrics from an OpenMetrics endpoint.
//
// Supports only GAUGE and COUNTER metrics.
type OpenMetrics struct {
	name        string
	url         string
	filters     [][]string
	client      *retryablehttp.Client
	logger      *observability.CoreLogger
	labelMap    map[string]map[string]int
	labelHashes map[string]map[string]string
}

func processSequenceFilters(sequence *spb.ListStringValue) [][]string {
	if sequence == nil {
		return nil
	}
	result := make([][]string, len(sequence.GetValue()))
	for i, filter := range sequence.GetValue() {
		result[i] = []string{filter}
	}
	return result
}

func processMappingFilters(mapping *spb.MapStringKeyMapStringKeyStringValue) [][]string {
	if mapping == nil {
		return nil
	}
	result := [][]string{}
	for metricRegex, labelFilters := range mapping.GetValue() {
		for labelName, labelRegex := range labelFilters.GetValue() {
			result = append(result, []string{metricRegex, labelName, labelRegex})
		}
	}
	return result
}

func NewOpenMetrics(
	logger *observability.CoreLogger,
	name string,
	url string,
	filters *spb.OpenMetricsFilters,
) *OpenMetrics {
	retryClient := retryablehttp.NewClient()
	retryClient.Logger = logger
	retryClient.CheckRetry = filetransfer.FileTransferRetryPolicy
	retryClient.RetryMax = filetransfer.DefaultRetryMax
	retryClient.RetryWaitMin = filetransfer.DefaultRetryWaitMin
	retryClient.RetryWaitMax = filetransfer.DefaultRetryWaitMax
	retryClient.HTTPClient.Timeout = filetransfer.DefaultNonRetryTimeout
	retryClient.Backoff = clients.ExponentialBackoffWithJitter

	// metrics are collected on a best-effort basis, but we do allow for some retries
	retryClient.RetryMax = 3
	retryClient.RetryWaitMin = 1 * time.Second
	retryClient.RetryWaitMax = 10 * time.Second
	retryClient.HTTPClient.Timeout = 5 * time.Second

	var processedFilters [][]string

	if filters != nil {
		switch v := filters.GetValue().(type) {
		case *spb.OpenMetricsFilters_Sequence:
			processedFilters = processSequenceFilters(v.Sequence)
		case *spb.OpenMetricsFilters_Mapping:
			processedFilters = processMappingFilters(v.Mapping)
		default:
			logger.Warn("Unknown filter type, using empty filter")
		}
	}

	om := &OpenMetrics{
		name:        name,
		url:         url,
		filters:     processedFilters,
		client:      retryClient,
		logger:      logger,
		labelMap:    make(map[string]map[string]int),
		labelHashes: make(map[string]map[string]string),
	}

	return om
}

func (o *OpenMetrics) Name() string { return o.name }

type FilterMap map[string]map[string]string

// // nestedDictToTuple converts a nested map to a slice of tuples
// func nestedDictToTuple(nestedDict FilterMap) [][]string {
// 	result := [][]string{}
// 	for k, v := range nestedDict {
// 		tuple := []string{k}
// 		for k2, v2 := range v {
// 			tuple = append(tuple, k2, v2)
// 		}
// 		result = append(result, tuple)
// 	}
// 	return result
// }

// // tupleToNestedDict converts a slice of tuples to a nested map
// func tupleToNestedDict(nestedTuple [][]string) FilterMap {
// 	result := FilterMap{}
// 	for _, tuple := range nestedTuple {
// 		k := tuple[0]
// 		result[k] = make(map[string]string)
// 		for i := 1; i < len(tuple); i += 2 {
// 			result[k][tuple[i]] = tuple[i+1]
// 		}
// 	}
// 	return result
// }

// shouldCaptureMetric checks if a metric should be captured based on the filters
func shouldCaptureMetric(
	endpointName, metricName string,
	metricLabels map[string]string,
	filters [][]string,
) bool {
	if len(filters) == 0 {
		return true // If no filters, capture all metrics
	}

	fullMetricName := fmt.Sprintf("%s.%s", endpointName, metricName)

	for _, filter := range filters {
		metricNameRegex := filter[0]
		if match, _ := regexp.MatchString(metricNameRegex, fullMetricName); !match {
			continue
		}

		if len(filter) == 1 {
			return true // If only metric name regex is provided, capture the metric
		}

		labelName, labelRegex := filter[1], filter[2]
		if labelValue, ok := metricLabels[labelName]; ok {
			if match, _ := regexp.MatchString(labelRegex, labelValue); match {
				return true
			}
		}
	}

	return false
}

func (o *OpenMetrics) Sample() (map[string]any, error) {
	resp, err := o.client.Get(o.url)
	if err != nil {
		return nil, err
	}
	if resp != nil {
		defer resp.Body.Close()
	}

	if resp != nil && resp.StatusCode == 200 {
		var parser expfmt.TextParser
		metricFamilies, err := parser.TextToMetricFamilies(resp.Body)
		if err != nil {
			o.logger.Error("Error parsing metrics", "error", err)
			return nil, err
		}

		result := make(map[string]any)

		for name, mf := range metricFamilies {
			for _, m := range mf.Metric {
				// only GAUGE and COUNTER metrics are supported
				if m.Counter == nil && m.Gauge == nil {
					continue
				}

				labels := make(map[string]string)
				for _, label := range m.GetLabel() {
					labels[label.GetName()] = label.GetValue()
				}

				if !shouldCaptureMetric(o.name, name, labels, o.filters) {
					continue
				}

				labelHash := o.generateLabelHash(labels)

				if _, ok := o.labelMap[name]; !ok {
					o.labelMap[name] = make(map[string]int)
				}
				if _, ok := o.labelMap[name][labelHash]; !ok {
					o.labelMap[name][labelHash] = len(o.labelMap[name])
					o.labelHashes[labelHash] = labels
				}
				index := o.labelMap[name][labelHash]

				var value float64
				if m.Gauge != nil {
					value = m.Gauge.GetValue()
				} else if m.Counter != nil {
					value = m.Counter.GetValue()
				}

				key := fmt.Sprintf("%s.%s.%d", o.name, name, index)
				result[key] = value
			}
		}

		fmt.Println(result)
		return result, nil
	}

	return nil, fmt.Errorf("unexpected status code: %d", resp.StatusCode)
}

func (o *OpenMetrics) generateLabelHash(labels map[string]string) string {
	labelStr := fmt.Sprintf("%v", labels)
	hash := md5.Sum([]byte(labelStr))
	return hex.EncodeToString(hash[:])
}

func (o *OpenMetrics) IsAvailable() bool {
	// try to fetch the metrics once to check if the endpoint is available
	_, err := o.Sample()
	if err != nil {
		o.logger.Warn(
			"openmetrics: failed to fetch metrics from endpoint",
			"url", o.url,
			"error", err,
		)
		return false
	}
	return true
}

func (o *OpenMetrics) Probe() *spb.MetadataRequest {
	return nil
}
