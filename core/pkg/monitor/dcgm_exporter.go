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

// DCGMExporter collects NVIDIA GPU metrics reported by the Data Center GPU Manager (DCGM)
// from a Prometheus API endpoint.
//
// It is common to set up infrastructure that exposes GPU metrics through a centralized
// Prometheus / OpenMetrics instance that aggregates Nvidia DCGM Exporter metrics from
// (potentially) multiple compute nodes (e.g. in SLURM jobs).
type DCGMExporter struct {
	// The full URL of the Prometheus API endpoint is parsed into the base URL and the query.
	// For example:
	// https://gateway:9400/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP{node="l1337", cluster="globular"}
	// will be parsed into:
	// - baseUrl: http://prometheus-gateway:9400
	// - queries: ["DCGM_FI_DEV_GPU_TEMP{node=\"l1337\", cluster=\"globular\"}"]

	// baseUrl is the base URL of the OpenMetrics API endpoint.
	baseUrl string

	// queries are the PromQL queries to fetch the relevant metrics.
	//
	// PromQL is the Prometheus Query Language.
	queries []string

	// prometheusAPI is the Prometheus API client.
	prometheusAPI v1.API

	// logger is the logger to log logs. ;)
	logger *observability.CoreLogger
}

type DCGMExporterParams struct {
	// URL of the Prometheus API endpoint.
	//
	// The user must provide the URL of the Prometheus API endpoint and the Prometheus query
	// to fetch the relevant metrics, for example:
	// http://prometheus-gateway:9400/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP{node="l1337", cluster="globular"}
	// It will be parsed into the base URL and the query.
	URL string

	// HTTP headers to include in the requests.
	//
	// Typically used for authentication.
	Headers map[string]string

	// Logger to use for logging.
	Logger *observability.CoreLogger

	// Client is the base retryable HTTP client to use for the Prometheus API client.
	Client *retryablehttp.Client
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

	// Case 1: /metrics endpoint.
	if strings.HasSuffix(params.URL, "/metrics") {
		// TODO: Implement
		return nil
	}

	// Case 2: Prometheus API (/api/v1/query) query.
	var err error

	// Split the URL into the base URL and the query.
	baseUrl, queries, err := ParsePromQLURL(params.URL)
	if err != nil {
		params.Logger.Error("monitor: openmetrics: error parsing URL", "error", err)
		return nil
	}
	params.Logger.Debug("monitor: openmetrics: parsed URL", "url", baseUrl, "queries", queries)

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
		Address:      baseUrl,
		RoundTripper: roundTripper,
	})
	if err != nil {
		params.Logger.Error("monitor: dcgm_exporter: error creating Prometheus API client", "error", err)
		return nil
	}

	// Create the Prometheus v1 API client.
	prometheusAPI := v1.NewAPI(apiClient)

	return &DCGMExporter{
		baseUrl:       baseUrl,
		queries:       queries,
		logger:        params.Logger,
		prometheusAPI: prometheusAPI,
	}
}

// ParsePromQLURL parses a Prometheus API URL to get the base URL and query parameters.
//
// The query is expected to be in the Prometheus Query Language (PromQL).
// parsedURL.Path is omitted as Prometheus' api.Client() assumes /api/v1/query.
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

// Queries returns the Prometheus queries used to fetch the metrics.
//
// Used for testing.
func (de *DCGMExporter) Queries() []string {
	return de.queries
}

// gpuMetric represents a GPU metric and metadata parsed from a Prometheus sample.
type gpuMetric struct {
	// name is the metric name.
	name string
	// value is the metric value.
	value float64
	// index is GPU index (e.g. 0, 1, 2, ...).
	index string
	// uuid is the UUID of the GPU.
	uuid string
	// modelName is the model name of the GPU.
	modelName string
	// node is the name of the node where the GPU is located.
	node string
	// hostname is the hostname of the node where the GPU is located.
	hostname string
}

// newGPUMetric parses a GPU metric from a Prometheus sample.
func newGPUMetric(sample *model.Sample) (*gpuMetric, error) {
	labels := make(map[string]string)

	for labelName, labelValue := range sample.Metric {
		if labelName != "__name__" {
			labels[string(labelName)] = string(labelValue)
		}
	}

	// Get GPU index from labels - usually in 'gpu' or 'device' label.
	// If it is missing, we cannot identify the GPU and should ignore the metric.
	gpuIndex := ""
	if idx, ok := labels["gpu"]; ok {
		gpuIndex = idx
	} else if idx, ok := labels["device"]; ok {
		// Strip "nvidia" prefix if present
		gpuIndex = strings.TrimPrefix(idx, "nvidia")
	}
	if gpuIndex == "" {
		return nil, fmt.Errorf("missing GPU index")
	}

	gm := &gpuMetric{
		name:  string(sample.Metric["__name__"]), // Prometheus stores it in the '__name__' label
		value: float64(sample.Value),             // Safe ops as sample.Value is a float64
		index: gpuIndex,
	}

	// Extract metadata from labels
	if uuid, ok := labels["uuid"]; ok {
		gm.uuid = uuid
	}
	if modelName, ok := labels["modelName"]; ok {
		gm.modelName = modelName
	}
	if node, ok := labels["node"]; ok {
		gm.node = node
	}
	if hostname, ok := labels["hostname"]; ok {
		gm.hostname = hostname
	}

	return gm, nil
}

// wandbName maps a GPU metric from DCGM to a WandB GPU metric name.
//
// The WandB GPU metric name is in the format: `gpu.<index>.<metricName>/l:<label>`.
// The label is used to differentiate between GPUs from different nodes.
//
// The full list of DCGM metrics and their descriptions can be found here:
// https://docs.nvidia.com/datacenter/dcgm/latest/dcgm-api/dcgm-api-field-ids.html
//
//gocyclo:ignore
func (gm *gpuMetric) wandbName() string {
	var mappedName string
	switch gm.name {
	case "DCGM_FI_DEV_GPU_TEMP":
		mappedName = fmt.Sprintf("gpu.%s.temp", gm.index)
	case "DCGM_FI_DEV_POWER_USAGE":
		mappedName = fmt.Sprintf("gpu.%s.powerWatts", gm.index)
	case "DCGM_FI_DEV_GPU_UTIL":
		mappedName = fmt.Sprintf("gpu.%s.gpu", gm.index)
	case "DCGM_FI_DEV_MEM_COPY_UTIL":
		mappedName = fmt.Sprintf("gpu.%s.memory", gm.index)
	case "DCGM_FI_DEV_SM_CLOCK":
		mappedName = fmt.Sprintf("gpu.%s.smClock", gm.index)
	case "DCGM_FI_DEV_FB_USED":
		mappedName = fmt.Sprintf("gpu.%s.memoryUsed", gm.index)
	case "DCGM_FI_DEV_FB_TOTAL":
		mappedName = fmt.Sprintf("gpu.%s.memoryTotal", gm.index)
	case "DCGM_FI_PROF_PCIE_TX_BYTES":
		mappedName = fmt.Sprintf("gpu.%s.pcieTxBytes", gm.index)
	case "DCGM_FI_PROF_PCIE_RX_BYTES":
		mappedName = fmt.Sprintf("gpu.%s.pcieRxBytes", gm.index)
	case "DCGM_FI_PROF_NVLINK_TX_BYTES":
		mappedName = fmt.Sprintf("gpu.%s.nvlinkTxBytes", gm.index)
	case "DCGM_FI_PROF_NVLINK_RX_BYTES":
		mappedName = fmt.Sprintf("gpu.%s.nvlinkRxBytes", gm.index)

	// TODO: require new aggregations on the frontend
	case "DCGM_FI_DEV_MEMORY_TEMP":
		mappedName = fmt.Sprintf("gpu.%s.memoryTemp", gm.index)
	case "DCGM_FI_DEV_GPU_MAX_OP_TEMP":
		mappedName = fmt.Sprintf("gpu.%s.maxOpTemp", gm.index)
	case "DCGM_FI_DEV_MEM_MAX_OP_TEMP":
		mappedName = fmt.Sprintf("gpu.%s.memoryMaxOpTemp", gm.index)
	case "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION":
		mappedName = fmt.Sprintf("gpu.%s.totalEnergyConsumption", gm.index)
	case "DCGM_FI_PROF_SM_ACTIVE":
		mappedName = fmt.Sprintf("gpu.%s.smActive", gm.index)
	case "DCGM_FI_PROF_SM_OCCUPANCY":
		mappedName = fmt.Sprintf("gpu.%s.smOccupancy", gm.index)
	case "DCGM_FI_PROF_PIPE_TENSOR_ACTIVE":
		mappedName = fmt.Sprintf("gpu.%s.pipeTensorActive", gm.index)
	case "DCGM_FI_PROF_PIPE_FP64_ACTIVE":
		mappedName = fmt.Sprintf("gpu.%s.pipeFp64Active", gm.index)
	case "DCGM_FI_PROF_PIPE_FP32_ACTIVE":
		mappedName = fmt.Sprintf("gpu.%s.pipeFp32Active", gm.index)
	case "DCGM_FI_PROF_PIPE_FP16_ACTIVE":
		mappedName = fmt.Sprintf("gpu.%s.pipeFp16Active", gm.index)
	case "DCGM_FI_DEV_FB_FREE":
		mappedName = fmt.Sprintf("gpu.%s.memoryFree", gm.index)
	default:
		// Skip unknown metrics
		return ""
	}

	// Add a label to the metric name. Use node or hostname as the label
	// to differentiate between GPUs from different nodes (e.g. in multi-node training).
	// Example: `gpu.0.owerWatts/l:node1`
	label := ""
	if gm.node != "" {
		label = gm.node
	} else if gm.hostname != "" {
		label = gm.hostname
	}
	if label != "" {
		mappedName = fmt.Sprintf("%s/l:%s", mappedName, label)
	}

	return mappedName
}

// Sample fetches and parses the metrics from the endpoint and returns them as a StatsRecord.
func (de *DCGMExporter) Sample() (*spb.StatsRecord, error) {
	ctx, cancel := context.WithTimeout(context.Background(), DefaultOpenMetricsTimeout)
	defer cancel()

	metrics := make(map[string]any)

	for _, query := range de.queries {
		result, warnings, err := de.prometheusAPI.Query(
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

		// model.Vector is expected.
		vector, ok := result.(model.Vector)
		if !ok {
			de.logger.Error("monitor: dcgm: unexpected result type", "type", fmt.Sprintf("%T", result))
			continue
		}

		// Process each sample in the vector.
		for _, sample := range vector {
			gm, err := newGPUMetric(sample)
			if err != nil {
				de.logger.Debug("monitor: dcgm_exporter: error parsing GPU metric", "error", err)
				continue
			}

			metrics[gm.wandbName()] = gm.value
		}
	}

	if len(metrics) == 0 {
		return nil, fmt.Errorf("no metrics found")
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
			"url", o.baseUrl,
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
		result, warnings, err := de.prometheusAPI.Query(
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
			gm, err := newGPUMetric(sample)
			if err != nil {
				de.logger.Debug("monitor: dcgm_exporter: error parsing GPU metric", "error", err)
				continue
			}

			// GPU Model Name and UUID uniquely identify a GPU.
			// Do not store the information if either is missing.
			if gm.modelName == "" || gm.uuid == "" {
				continue
			}

			gpuInfo := &spb.GpuNvidiaInfo{
				Name: gm.modelName,
				Uuid: gm.uuid,
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
