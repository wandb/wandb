package monitor

import (
	"context"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/prometheus/client_golang/api"
	v1 "github.com/prometheus/client_golang/api/prometheus/v1"
	"github.com/prometheus/common/config"
	"github.com/prometheus/common/model"
)

type DCGMExporterParams struct {
	// Full URL including query parameters.
	URL string
	// HTTP headers to include in the requests.
	Headers map[string]string
	// Logger to use for logging.
	Logger *observability.CoreLogger
	// Client is the base retryable HTTP client to use for requests.
	Client *retryablehttp.Client
}

type DCGMExporter struct {
	// url is the base URL of the OpenMetrics API endpoint.
	url     string
	queries []string

	// v1api is the Prometheus API client.
	v1api v1.API

	// logger is the logger to log logs. ;)
	logger *observability.CoreLogger
}

// parsePromQLURL parses a Prometheus API URL to get the base URL and query parameters.
//
// URL path is omitted as Prometheus' api.Client() assumes /api/v1/query.
func ParsePromQLURL(fullURL string) (baseURL string, queries []string, err error) {
	parsedURL, err := url.Parse(fullURL)
	if err != nil {
		return "", nil, err
	}

	baseURL = parsedURL.Scheme + "://" + parsedURL.Host

	// Parse the query string separately
	params, err := url.ParseQuery(parsedURL.RawQuery)
	if err != nil {
		return "", nil, err
	}

	// Check if query parameter exists
	queries = params["query"]
	if len(queries) == 0 {
		return "", nil, fmt.Errorf("no query parameter provided")
	}

	return baseURL, queries, nil
}

func NewDCGMExporter(params DCGMExporterParams) *DCGMExporter {
	// Set up a default retryable client if none is provided.
	if params.Client == nil {
		params.Client = retryablehttp.NewClient()
		params.Client.Logger = params.Logger
		params.Client.CheckRetry = retryablehttp.ErrorPropagatedRetryPolicy
		params.Client.RetryMax = DefaultOpenMetricsRetryMax
		params.Client.RetryWaitMin = DefaultOpenMetricsRetryWaitMin
		params.Client.RetryWaitMax = DefaultOpenMetricsRetryWaitMax
		params.Client.HTTPClient.Timeout = DefaultOpenMetricsTimeout
		params.Client.Backoff = clients.ExponentialBackoffWithJitter
	}

	de := &DCGMExporter{logger: params.Logger}

	// Case 1: /metrics endpoint.
	if strings.HasSuffix(params.URL, "/metrics") {
		// TODO: Implement
		return nil
	}

	// Case 2: Prometheus API (/api/v1/query) query.
	var err error

	// Split the URL into the base URL and the query.
	de.url, de.queries, err = ParsePromQLURL(params.URL)
	if err != nil {
		de.logger.Error("monitor: openmetrics: error parsing URL", "error", err)
		return nil
	}
	de.logger.Debug("monitor: openmetrics: parsed URL", "url", de.url, "queries", de.queries)

	// Create headers config.
	headersConfig := &config.Headers{
		Headers: make(map[string]config.Header),
	}
	for key, value := range params.Headers {
		headersConfig.Headers[key] = config.Header{
			Values: []string{value},
		}
	}

	// Create a chain of RoundTrippers: headers -> retryable client.
	roundTripper := config.NewHeadersRoundTripper(
		headersConfig,
		params.Client.StandardClient().Transport,
	)

	apiClient, err := api.NewClient(api.Config{
		Address:      de.url,
		RoundTripper: roundTripper,
	})
	if err != nil {
		de.logger.Error("monitor: dcgm_exporter: error creating Prometheus API client", "error", err)
		return nil
	}

	// Create the Prometheus API client.
	de.v1api = v1.NewAPI(apiClient)

	return de
}

func (de *DCGMExporter) Queries() []string {
	return de.queries
}

func (de *DCGMExporter) Name() string {
	return "dcgm_exporter"
}

// Sample fetches and parses the metrics from the endpoint and returns them as a StatsRecord.
func (de *DCGMExporter) Sample() (*spb.StatsRecord, error) {
	ctx, cancel := context.WithTimeout(context.Background(), DefaultOpenMetricsTimeout)
	defer cancel()

	metrics := make(map[string]any)

	for _, query := range de.queries {
		result, warnings, err := de.v1api.Query(
			ctx,
			query,
			time.Now(),
			v1.WithTimeout(DefaultOpenMetricsTimeout),
		)
		if err != nil {
			de.logger.Error("monitor: dcgm_exporter: error querying Prometheus API endpoint", "error", err)
			return nil, err
		}
		if len(warnings) > 0 {
			de.logger.Warn("monitor: openmetrics: warnings querying Prometheus API endpoint", "warnings", warnings)
		}

		// Process the results based on type
		vector, ok := result.(model.Vector)
		if !ok {
			de.logger.Error("monitor: dcgm: unexpected result type", "type", fmt.Sprintf("%T", result))
			continue
		}

		// Process each sample in the vector
		for _, sample := range vector {
			metricName := string(sample.Metric["__name__"])
			labels := make(map[string]string)

			for labelName, labelValue := range sample.Metric {
				if labelName != "__name__" {
					labels[string(labelName)] = string(labelValue)
				}
			}

			// Get GPU index from labels - usually in 'gpu' or 'device' label
			gpuIndex := ""
			if idx, ok := labels["gpu"]; ok {
				gpuIndex = idx
			} else if idx, ok := labels["device"]; ok {
				// Strip "nvidia" prefix if present
				gpuIndex = strings.TrimPrefix(idx, "nvidia")
			}
			if gpuIndex == "" {
				continue
			}

			// Map DCGM metrics to our format
			var mappedName string
			switch metricName {
			case "DCGM_FI_DEV_POWER_USAGE":
				mappedName = fmt.Sprintf("gpu.%s.powerWatts", gpuIndex)
			case "DCGM_FI_DEV_GPU_TEMP":
				mappedName = fmt.Sprintf("gpu.%s.temp", gpuIndex)
			// TODO: requires aggregation on the frontend
			// case "DCGM_FI_DEV_MEMORY_TEMP":
			// 	mappedName = fmt.Sprintf("gpu.%s.memoryTemp", gpuIndex)
			case "DCGM_FI_DEV_MEM_COPY_UTIL":
				mappedName = fmt.Sprintf("gpu.%s.memory", gpuIndex)
			// TODO: requires aggregation on the frontend
			// case "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION":
			// 	mappedName = fmt.Sprintf("gpu.%s.totalEnergyConsumption", gpuIndex)
			default:
				// Skip unknown metrics
				continue
			}

			// Convert the value - note that DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION is in mJ
			value := float64(sample.Value) // Safe ops as sample.Value is a float64
			if metricName == "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION" {
				// Convert mJ to J
				value /= 1000.0
			}

			// Use node or hostname as the label to differentiate between GPUs
			// from different nodes (e.g. in multi-node training)
			// Example: `gpu.0.owerWatts/l:node1`
			label := ""
			if node, ok := labels["node"]; ok {
				label = node
			} else if hostname, ok := labels["hostname"]; ok {
				label = hostname
			}

			// Add the label to the metric name
			if label != "" {
				mappedName = fmt.Sprintf("%s/l:%s", mappedName, label)
			}

			metrics[mappedName] = value
		}
	}

	if len(metrics) == 0 {
		return nil, nil
	}

	return marshal(metrics, timestamppb.Now()), nil
}

// IsAvailable checks if the endpoint is accessible.
func (o *DCGMExporter) IsAvailable() bool {
	// try to fetch the metrics once to check if the endpoint is available
	_, err := o.Sample()
	if err != nil {
		o.logger.Warn(
			"monitor: openmetrics: failed to fetch metrics from endpoint",
			"url", o.url,
			"error", err,
		)
		return false
	}
	return true
}

// Probe fetches the Nvidia GPU metadata from the endpoint and returns it as a MetadataRequest.
//
// A GPU is identified by its model name and UUID.
func (de *DCGMExporter) Probe() *spb.MetadataRequest {
	ctx, cancel := context.WithTimeout(context.Background(), DefaultOpenMetricsTimeout)
	defer cancel()

	gpus := make(map[*spb.GpuNvidiaInfo]bool)

	for _, query := range de.queries {
		result, warnings, err := de.v1api.Query(
			ctx,
			query,
			time.Now(),
			v1.WithTimeout(DefaultOpenMetricsTimeout),
		)
		if err != nil {
			de.logger.Error("monitor: dcgm_exporter: error querying Prometheus API endpoint", "error", err)
			return nil
		}
		if len(warnings) > 0 {
			de.logger.Warn("monitor: openmetrics: warnings querying Prometheus API endpoint", "warnings", warnings)
		}

		// Process the results based on type
		vector, ok := result.(model.Vector)
		if !ok {
			de.logger.Error("monitor: dcgm: unexpected result type", "type", fmt.Sprintf("%T", result))
			continue
		}

		// Process each sample in the vector
		for _, sample := range vector {
			labels := make(map[string]string)

			for labelName, labelValue := range sample.Metric {
				if labelName != "__name__" {
					labels[string(labelName)] = string(labelValue)
				}
			}

			// Get GPU index from labels - usually in 'gpu' or 'device' label
			gpuIndex := ""
			if idx, ok := labels["gpu"]; ok {
				gpuIndex = idx
			} else if idx, ok := labels["device"]; ok {
				// Strip "nvidia" prefix if present
				gpuIndex = strings.TrimPrefix(idx, "nvidia")
			}
			if gpuIndex == "" {
				continue
			}

			// GPU Model Name and UUID uniquely identify a GPU.
			// Do not store the information if either is missing.
			gpuInfo := &spb.GpuNvidiaInfo{}
			if gpuInfo.Name, ok = labels["modelName"]; !ok {
				continue
			}
			if gpuInfo.Uuid, ok = labels["uuid"]; !ok {
				continue
			}

			gpus[gpuInfo] = true
		}
	}

	if len(gpus) == 0 {
		return nil
	}

	gpuNvidia := make([]*spb.GpuNvidiaInfo, 0, len(gpus))
	for gpu := range gpus {
		gpuNvidia = append(gpuNvidia, gpu)
	}

	return &spb.MetadataRequest{
		GpuNvidia: gpuNvidia,
		GpuCount:  uint32(len(gpuNvidia)),
		GpuType:   gpuNvidia[0].Name, // TODO: handle multiple GPU types
	}
}
