package monitor

import (
	"crypto/md5"
	"encoding/hex"
	"fmt"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	lru "github.com/hashicorp/golang-lru"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"

	"github.com/prometheus/common/expfmt"
)

// Filter represents a filter to apply to metrics collected from an OpenMetrics endpoint.
//
// Provides a fine-grained control over which metrics to collect.
// OpenMetrics filters can be specified via wandb.Settings in one of the two formats:
//   - {"metric regex pattern, including endpoint name as prefix": {"label": "label value regex pattern"}}
//   - ("metric regex pattern 1", "metric regex pattern 2", ...)
//
// These are converted to a list of Filter objects using the processMappingFilters
// and processSequenceFilters functions, respectively.
//
// The following code snippet demonstrates how to configure OpenMetrics filters
// to capture only the metrics DCGM_FI_DEV_POWER_USAGE with the labels gpu="0" or gpu="1"
// from node1 and 5 metrics with the label gpu=".*" from node2.
//
// run = wandb.init(
//
//	project="dcgm",
//	settings=wandb.Settings(
//	    _stats_open_metrics_endpoints={
//	        "node1": "http://192.168.0.1:9400/metrics",
//	        "node2": "http://192.168.0.2:9400/metrics",
//	    },
//	    _stats_open_metrics_filters={
//	        "node1.DCGM_FI_DEV_POWER_USAGE": {
//	            "gpu": "[0,1]",
//	        },
//	        "node2.DCGM_FI_DEV_(POWER_USAGE|MEM_COPY_UTIL|TOTAL_ENERGY_CONSUMPTION|GPU_TEMP|MEMORY_TEMP)": {
//	            "gpu": ".*",
//	        },
//	    },
//	),
//
// )
//
// The OpenMetrics endpoint at http://192.168.0.1:9400/metrics (designated `node1` by the user
// in the settings) might expose the following metrics:
//
// # HELP DCGM_FI_DEV_POWER_USAGE Power draw (in W).
// # TYPE DCGM_FI_DEV_POWER_USAGE gauge
// DCGM_FI_DEV_POWER_USAGE{gpu="0",UUID="GPU-c601d117-58ff-cd30-ae20-529ab192ba51"} 99.9
// DCGM_FI_DEV_POWER_USAGE{gpu="1",UUID="GPU-a7c8aa83-d112-b585-8456-5fc2f3e6d18e"} 0.1
// DCGM_FI_DEV_POWER_USAGE{gpu="2",UUID="GPU-a7c8aa83-d112-b463-3456-5fc2f3f2k43s"} 40.2
//
// The specified filter will capture only the metrics with lables gpu="0" and gpu="1" from node1.
type Filter struct {
	MetricNameRegex string
	LabelFilters    []LabelFilter
}

type LabelFilter struct {
	LabelName  string
	LabelRegex string
}

// processSequenceFilters converts a sequence of metric regex patterns to a list of Filter objects.
func processSequenceFilters(sequence *spb.ListStringValue) []Filter {
	if sequence == nil {
		return nil
	}
	result := make([]Filter, len(sequence.GetValue()))
	for i, filter := range sequence.GetValue() {
		result[i] = Filter{MetricNameRegex: filter}
	}
	return result
}

// processMappingFilters converts a mapping of metric regex patterns to label regex patterns
// to a list of Filter objects.
func processMappingFilters(mapping *spb.MapStringKeyMapStringKeyStringValue) []Filter {
	if mapping == nil {
		return nil
	}
	result := []Filter{}
	for metricRegex, labelFilters := range mapping.GetValue() {
		filter := Filter{MetricNameRegex: metricRegex}
		for labelName, labelRegex := range labelFilters.GetValue() {
			filter.LabelFilters = append(filter.LabelFilters, LabelFilter{labelName, labelRegex})
		}
		result = append(result, filter)
	}
	return result
}

// Constants for the default OpenMetrics HTTP client configuration.
//
// Metrics are collected on a best-effort basis, but we do allow for some retries.
const (
	DefaultOpenMetricsRetryMax     = 3
	DefaultOpenMetricsRetryWaitMin = 1 * time.Second
	DefaultOpenMetricsRetryWaitMax = 10 * time.Second
	DefaultOpenMetricsTimeout      = 5 * time.Second
)

// OpenMetrics is a monitor that collects metrics from an OpenMetrics endpoint.
//
// Supports only GAUGE and COUNTER metrics.
//
// The labels of the metrics are used to uniquely identify them. The labels are hashed
// to generate a unique identifier for each metric. The unique identifier is used to
// aggregate the metrics in the frontend.
type OpenMetrics struct {
	name        string
	url         string
	filters     []Filter
	client      *retryablehttp.Client
	logger      *observability.CoreLogger
	labelMap    map[string]map[string]int    // metricName -> labelHash -> index
	labelHashes map[string]map[string]string // labelHash -> labels
	cache       *lru.Cache
}

func NewOpenMetrics(
	logger *observability.CoreLogger,
	name string,
	url string,
	filters *spb.OpenMetricsFilters,
	retryClient *retryablehttp.Client,
) *OpenMetrics {
	var client *retryablehttp.Client

	if retryClient == nil {
		client = retryablehttp.NewClient()
		client.Logger = logger
		client.CheckRetry = retryablehttp.ErrorPropagatedRetryPolicy
		client.RetryMax = DefaultOpenMetricsRetryMax
		client.RetryWaitMin = DefaultOpenMetricsRetryWaitMin
		client.RetryWaitMax = DefaultOpenMetricsRetryWaitMax
		client.HTTPClient.Timeout = DefaultOpenMetricsTimeout
		client.Backoff = clients.ExponentialBackoffWithJitter
	} else {
		client = retryClient
	}

	var processedFilters []Filter

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

	// cache to use with ShouldCaptureMetric
	cache, err := lru.New(100)
	if err != nil {
		logger.Error("openmetrics: error creating cache", "error", err)
		return nil
	}

	om := &OpenMetrics{
		name:        name,
		url:         url,
		filters:     processedFilters,
		client:      client,
		logger:      logger,
		labelMap:    make(map[string]map[string]int),
		labelHashes: make(map[string]map[string]string),
		cache:       cache,
	}

	return om
}

func (o *OpenMetrics) Name() string { return o.name }

func (o *OpenMetrics) SetFilters(filters []Filter) {
	o.filters = filters
}

func (o *OpenMetrics) Cache() *lru.Cache {
	return o.cache
}

// ShouldCaptureMetric checks if a metric should be captured based on the filters.
func (o *OpenMetrics) ShouldCaptureMetric(metricName string, metricLabels map[string]string) bool {
	if len(o.filters) == 0 {
		return true // If no filters, capture all metrics
	}

	// generate a hash of metricName and metricLabels to avoid recomputing it
	// for the same metric
	hash := o.GenerateLabelHash(metricLabels)
	if shouldCapture, ok := o.cache.Get(metricName + hash); ok {
		return shouldCapture.(bool)
	}

	var shouldCapture bool

	fullMetricName := fmt.Sprintf("%s.%s", o.Name(), metricName)

	for _, filter := range o.filters {
		if match, _ := regexp.MatchString(filter.MetricNameRegex, fullMetricName); !match {
			continue
		}

		// if only metric name regex is provided, capture the metric.
		if len(filter.LabelFilters) == 0 {
			o.cache.Add(metricName+hash, true)
			return true
		}

		shouldCapture = true
		for _, labelFilter := range filter.LabelFilters {
			if labelValue, ok := metricLabels[labelFilter.LabelName]; !ok {
				shouldCapture = false
				break
			} else {
				if match, _ := regexp.MatchString(labelFilter.LabelRegex, labelValue); !match {
					shouldCapture = false
					break
				}
			}
		}

		o.cache.Add(metricName+hash, shouldCapture)

		if shouldCapture {
			return true
		}
	}

	o.cache.Add(metricName+hash, false)

	return false
}

// Sample fetches and processes metrics from the OpenMetrics endpoint.
func (o *OpenMetrics) Sample() (map[string]any, error) {
	resp, err := o.client.Get(o.url)
	if err != nil {
		return nil, err
	}
	if resp != nil {
		defer resp.Body.Close()
	}

	if resp == nil {
		return nil, fmt.Errorf("could not fetch metrics from endpoint")
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

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

			if !o.ShouldCaptureMetric(name, labels) {
				continue
			}

			labelHash := o.GenerateLabelHash(labels)

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

			// the frontend understands the format openmetrics.<endpoint>.<metric>.<index>
			// and aggregates the metrics based on <index>, which is a unique identifier
			// for the metric based on its labels. the openmetrics prefix is stripped off
			// and not displayed in the frontend.
			key := fmt.Sprintf("openmetrics.%s.%s.%d", o.Name(), name, index)
			result[key] = value
		}
	}

	return result, nil
}

// generateLabelHash creates a hash of the label map for consistent indexing.
func (o *OpenMetrics) GenerateLabelHash(labels map[string]string) string {
	var sb strings.Builder
	for k, v := range labels {
		sb.WriteString(k)
		sb.WriteString(v)
	}
	hash := md5.Sum([]byte(sb.String()))
	return hex.EncodeToString(hash[:])
}

// IsAvailable checks if the OpenMetrics endpoint is accessible.
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
