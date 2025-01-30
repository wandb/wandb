package monitor

import (
	"context"
	"fmt"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	lru "github.com/hashicorp/golang-lru"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/prometheus/client_golang/api"
	v1 "github.com/prometheus/client_golang/api/prometheus/v1"
	"github.com/prometheus/common/model"
)

type DCGMExporterParams struct {
	// Full URL including query parameters.
	URL string
	// HTTP headers to include in the requests.
	Headers map[string]string
	// Logger to use for logging.
	Logger *observability.CoreLogger
	// Client is the HTTP client to use for requests.
	Client *retryablehttp.Client
}

type DCGMExporter struct {
	// url is the base URL of the OpenMetrics API endpoint.
	url     string
	queries []string

	// headers is a map of HTTP headers to include in the requests.
	headers map[string]string

	// client is the HTTP client to use for requests.
	client *retryablehttp.Client

	// logger is the logger to log logs. ;)
	logger *observability.CoreLogger

	// labelMap is a map of metric names to label hashes to label indexes.
	//
	// metricName -> labelHash -> index
	labelMap map[string]map[string]int

	// labelHashes is a map of label hashes to labels.
	//
	// labelHash -> labels
	labelHashes map[string]map[string]string

	// cache is an LRU cache to use with ShouldCaptureMetric.
	cache *lru.Cache
}

func separateURL(fullURL string) (baseURL string, queries []string, err error) {
	parsedURL, err := url.Parse(fullURL)
	if err != nil {
		return "", nil, err
	}

	baseURL = parsedURL.Scheme + "://" + parsedURL.Host //+ parsedURL.Path
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

	de := &DCGMExporter{
		headers:     params.Headers,
		client:      params.Client,
		logger:      params.Logger,
		labelMap:    make(map[string]map[string]int),
		labelHashes: make(map[string]map[string]string),
	}

	// cache to use with ShouldCaptureMetric
	cache, err := lru.New(128)
	if err != nil {
		de.logger.Error("monitor: openmetrics: error creating cache", "error", err)
		return nil
	}
	de.cache = cache

	// Case 1: /metrics endpoint.
	if strings.HasSuffix(params.URL, "/metrics") {
		// TODO: Implement
		return nil
	}

	// Case 2: Prometheus API query.

	// Split the URL into the base URL and the query.
	de.url, de.queries, err = separateURL(params.URL)
	if err != nil {
		params.Logger.Error("monitor: openmetrics: error parsing URL", "error", err)
		return nil
	}
	fmt.Println(de.url, de.queries)

	return de
}

func (de *DCGMExporter) Name() string {
	return "dcgm_exporter"
}

func (de *DCGMExporter) Sample() (*spb.StatsRecord, error) {
	client, err := api.NewClient(api.Config{
		Address: de.url,
	})
	if err != nil {
		fmt.Printf("Error creating client: %v\n", err)
		os.Exit(1)
	}

	v1api := v1.NewAPI(client)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	metrics := make(map[string]any)

	for _, query := range de.queries {
		result, warnings, err := v1api.Query(
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
		// fmt.Printf("Result:\n%v\n", result)

		// Process the results based on type
		vector, ok := result.(model.Vector)
		if !ok {
			de.logger.Error("monitor: dcgm: unexpected result type", "type", fmt.Sprintf("%T", result))
			continue
		}

		// Process each sample in the vector
		for _, sample := range vector {
			// metricName := string(sample.Metric["__name__"])
			// labels := make(map[string]string)

			// // Convert model.Metric labels to map[string]string
			// for labelName, labelValue := range sample.Metric {
			// 	if labelName != "__name__" {
			// 		labels[string(labelName)] = string(labelValue)
			// 	}
			// }

			// // Generate a unique label hash for this combination
			// labelHash := GenerateLabelHash(labels)

			// // Initialize metric name in label map if not exists
			// if _, ok := de.labelMap[metricName]; !ok {
			// 	de.labelMap[metricName] = make(map[string]int)
			// }

			// // Assign index for this label combination if not exists
			// if _, ok := de.labelMap[metricName][labelHash]; !ok {
			// 	de.labelMap[metricName][labelHash] = len(de.labelMap[metricName])
			// 	de.labelHashes[labelHash] = labels
			// }

			// index := de.labelMap[metricName][labelHash]

			// // Format key as expected by frontend
			// key := fmt.Sprintf("openmetrics.%s.%s.%d", de.Name(), metricName, index)
			// metrics[key] = float64(sample.Value)
			// fmt.Println(key, metrics[key])

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
			// case "DCGM_FI_DEV_MEMORY_TEMP":
			// 	mappedName = fmt.Sprintf("gpu.%s.memoryTemp", gpuIndex)
			case "DCGM_FI_DEV_MEM_COPY_UTIL":
				mappedName = fmt.Sprintf("gpu.%s.memory", gpuIndex)
			// case "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION":
			// 	mappedName = fmt.Sprintf("gpu.%s.totalEnergyConsumption", gpuIndex)
			default:
				// Skip unknown metrics
				continue
			}

			// Convert the value - note that DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION is in mJ
			value := float64(sample.Value)
			if metricName == "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION" {
				// Convert mJ to J
				value = value / 1000.0
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
				metricName = fmt.Sprintf("%s/l:%s", metricName, label)
			}

			metrics[mappedName] = value

			labelHash := GenerateLabelHash(labels)
			if _, ok := de.labelMap[metricName]; !ok {
				de.labelMap[metricName] = make(map[string]int)
			}
			if _, ok := de.labelMap[metricName][labelHash]; !ok {
				de.labelMap[metricName][labelHash] = len(de.labelMap[metricName])
				de.labelHashes[labelHash] = labels
			}
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

func (o *DCGMExporter) Probe() *spb.MetadataRequest {
	// TODO: Call Sample() and report label mappings.
	return nil
}
