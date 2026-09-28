package monitor

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"

	"github.com/hashicorp/go-retryablehttp"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// DCGMExporter collects NVIDIA GPU metrics reported by the Data Center GPU Manager (DCGM)
// from a Prometheus API endpoint.
//
// It is common to set up infrastructure that exposes GPU metrics through a centralized
// Prometheus / OpenMetrics instance that aggregates Nvidia DCGM Exporter metrics from
// (potentially) multiple compute nodes (e.g. in SLURM jobs).
type DCGMExporter struct {
	// The full URL of the Prometheus API endpoint is parsed into the query URL and the queries.
	// For example:
	// https://gateway:9400/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP{node="l1337", cluster="globular"}
	// will be parsed into:
	// - queryURL: https://gateway:9400/api/v1/query
	// - queries: ["DCGM_FI_DEV_GPU_TEMP{node=\"l1337\", cluster=\"globular\"}"]

	// queryURL is the Prometheus instant query endpoint.
	queryURL string

	// queries are the PromQL queries to fetch the relevant metrics.
	//
	// PromQL is the Prometheus Query Language.
	queries []string

	// headers are sent with every request, typically for authentication.
	headers map[string]string

	// client sends the requests to the Prometheus API.
	client *retryablehttp.Client

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

	// Client is the retryable HTTP client to use for the Prometheus API requests.
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
	baseURL, queries, err := ParsePromQLURL(params.URL)
	if err != nil {
		params.Logger.Error("monitor: openmetrics: error parsing URL", "error", err)
		return nil
	}
	params.Logger.Debug("monitor: openmetrics: parsed URL", "url", baseURL, "queries", queries)

	return &DCGMExporter{
		queryURL: baseURL + "/api/v1/query",
		queries:  queries,
		headers:  params.Headers,
		client:   params.Client,
		logger:   params.Logger,
	}
}

// ParsePromQLURL parses a Prometheus API URL to get the base URL and query parameters.
//
// The query is expected to be in the Prometheus Query Language (PromQL).
// The URL's path is ignored: queries are sent to <baseURL>/api/v1/query.
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

// promSample is one element of the vector returned by a Prometheus instant query.
//
// Value holds the sample's timestamp followed by its value encoded as a string.
type promSample struct {
	Metric map[string]string `json:"metric"`
	Value  []json.RawMessage `json:"value"`
}

// query runs a PromQL instant query and returns the resulting vector.
func (de *DCGMExporter) query(ctx context.Context, query string) ([]promSample, error) {
	reqURL := de.queryURL + "?" + url.Values{"query": {query}}.Encode()
	req, err := retryablehttp.NewRequestWithContext(ctx, http.MethodGet, reqURL, nil)
	if err != nil {
		return nil, err
	}
	for key, value := range de.headers {
		req.Header.Set(key, value)
	}

	resp, err := de.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()

	var body struct {
		Status string `json:"status"`
		Data   struct {
			ResultType string       `json:"resultType"`
			Result     []promSample `json:"result"`
		} `json:"data"`
		ErrorType string   `json:"errorType"`
		Error     string   `json:"error"`
		Warnings  []string `json:"warnings"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, fmt.Errorf("HTTP %d: %w", resp.StatusCode, err)
	}
	if body.Status != "success" {
		return nil, fmt.Errorf("HTTP %d: %s: %s", resp.StatusCode, body.ErrorType, body.Error)
	}
	if body.Data.ResultType != "vector" {
		return nil, fmt.Errorf("unexpected result type %q", body.Data.ResultType)
	}
	if len(body.Warnings) > 0 {
		de.logger.Warn(
			"monitor: dcgm_exporter: warnings querying Prometheus API endpoint",
			"warnings", body.Warnings,
		)
	}

	return body.Data.Result, nil
}

// gpuMetrics runs all queries and parses the GPU metrics in their results.
func (de *DCGMExporter) gpuMetrics(ctx context.Context) ([]*gpuMetric, error) {
	var metrics []*gpuMetric

	for _, query := range de.queries {
		samples, err := de.query(ctx, query)
		if err != nil {
			de.logger.Error(
				"monitor: dcgm_exporter: error querying Prometheus API endpoint",
				"error", err,
			)
			return nil, err
		}

		for _, sample := range samples {
			gm, err := newGPUMetric(sample)
			if err != nil {
				de.logger.Debug("monitor: dcgm_exporter: error parsing GPU metric", "error", err)
				continue
			}
			metrics = append(metrics, gm)
		}
	}

	return metrics, nil
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
func newGPUMetric(sample promSample) (*gpuMetric, error) {
	labels := sample.Metric

	// Get GPU index from labels - usually in 'gpu' or 'device' label.
	// If it is missing, we cannot identify the GPU and should ignore the metric.
	gpuIndex := labels["gpu"]
	if gpuIndex == "" {
		// Strip "nvidia" prefix if present
		gpuIndex = strings.TrimPrefix(labels["device"], "nvidia")
	}
	if gpuIndex == "" {
		return nil, fmt.Errorf("missing GPU index")
	}

	if len(sample.Value) != 2 {
		return nil, fmt.Errorf("malformed sample value")
	}
	var text string
	if err := json.Unmarshal(sample.Value[1], &text); err != nil {
		return nil, err
	}
	value, err := strconv.ParseFloat(text, 64)
	if err != nil {
		return nil, err
	}

	return &gpuMetric{
		name:      labels["__name__"], // Prometheus stores it in the '__name__' label
		value:     value,
		index:     gpuIndex,
		uuid:      labels["uuid"],
		modelName: labels["modelName"],
		node:      labels["node"],
		hostname:  labels["hostname"],
	}, nil
}

// host returns the node the GPU belongs to, from the node or hostname label.
func (gm *gpuMetric) host() string {
	if gm.node != "" {
		return gm.node
	}
	return gm.hostname
}

// apply sets the typed field for a DCGM field id, converting DCGM units (MiB
// for framebuffer sizes, mJ for energy, 0 to 1 ratios for profiling metrics)
// to the schema's. Unknown fields are ignored.
//
// https://docs.nvidia.com/datacenter/dcgm/latest/dcgm-api/dcgm-api-field-ids.html
//
//gocyclo:ignore
func (gm *gpuMetric) apply(acc *spb.AcceleratorMetrics) {
	const mib = 1 << 20
	nvidia := func() *spb.NvidiaMetrics {
		if acc.GetNvidia() == nil {
			acc.Ext = &spb.AcceleratorMetrics_Nvidia{Nvidia: &spb.NvidiaMetrics{}}
		}
		return acc.GetNvidia()
	}
	v := gm.value

	switch gm.name {
	case "DCGM_FI_DEV_GPU_TEMP":
		acc.TemperatureC = &v
	case "DCGM_FI_DEV_POWER_USAGE":
		acc.PowerW = &v
	case "DCGM_FI_DEV_GPU_UTIL":
		acc.UtilizationPercent = &v
	case "DCGM_FI_DEV_MEM_COPY_UTIL":
		acc.MemoryActivityPercent = &v
	case "DCGM_FI_DEV_SM_CLOCK":
		nvidia().SmClockMhz = &v
	case "DCGM_FI_DEV_FB_USED":
		acc.MemoryUsedBytes = proto.Uint64(uint64(v * mib))
	case "DCGM_FI_DEV_FB_TOTAL":
		acc.MemoryTotalBytes = proto.Uint64(uint64(v * mib))
	case "DCGM_FI_DEV_FB_FREE":
		nvidia().MemoryFreeBytes = proto.Uint64(uint64(v * mib))
	case "DCGM_FI_PROF_PCIE_TX_BYTES":
		nvidia().PcieTxBytesPerS = &v
	case "DCGM_FI_PROF_PCIE_RX_BYTES":
		nvidia().PcieRxBytesPerS = &v
	case "DCGM_FI_PROF_NVLINK_TX_BYTES":
		nvidia().NvlinkTxBytesPerS = &v
	case "DCGM_FI_PROF_NVLINK_RX_BYTES":
		nvidia().NvlinkRxBytesPerS = &v
	case "DCGM_FI_DEV_MEMORY_TEMP":
		nvidia().MemoryTemperatureC = &v
	case "DCGM_FI_DEV_GPU_MAX_OP_TEMP":
		nvidia().MaxOperatingTemperatureC = &v
	case "DCGM_FI_DEV_MEM_MAX_OP_TEMP":
		nvidia().MemoryMaxOperatingTemperatureC = &v
	case "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION":
		acc.EnergyJ = proto.Float64(v / 1000)
	case "DCGM_FI_PROF_SM_ACTIVE":
		nvidia().SmActivePercent = proto.Float64(v * 100)
	case "DCGM_FI_PROF_SM_OCCUPANCY":
		nvidia().SmOccupancyPercent = proto.Float64(v * 100)
	case "DCGM_FI_PROF_PIPE_TENSOR_ACTIVE":
		nvidia().PipeTensorActivePercent = proto.Float64(v * 100)
	case "DCGM_FI_PROF_PIPE_FP64_ACTIVE":
		nvidia().PipeFp64ActivePercent = proto.Float64(v * 100)
	case "DCGM_FI_PROF_PIPE_FP32_ACTIVE":
		nvidia().PipeFp32ActivePercent = proto.Float64(v * 100)
	case "DCGM_FI_PROF_PIPE_FP16_ACTIVE":
		nvidia().PipeFp16ActivePercent = proto.Float64(v * 100)
	}
}

// Sample queries the exporter and returns one accelerator entry per GPU.
func (de *DCGMExporter) Sample() (*spb.SystemMetricsRecord, error) {
	ctx, cancel := context.WithTimeout(context.Background(), DefaultOpenMetricsTimeout)
	defer cancel()

	gpuMetrics, err := de.gpuMetrics(ctx)
	if err != nil {
		return nil, err
	}

	byIndex := make(map[string]*spb.AcceleratorMetrics)
	var accelerators []*spb.AcceleratorMetrics
	for _, gm := range gpuMetrics {
		acc, ok := byIndex[gm.index]
		if !ok {
			index, err := strconv.ParseUint(gm.index, 10, 32)
			if err != nil {
				continue
			}
			acc = &spb.AcceleratorMetrics{
				Type:   spb.AcceleratorType_NVIDIA_GPU,
				Index:  uint32(index),
				Uuid:   gm.uuid,
				Host:   gm.host(),
				Source: "dcgm-exporter",
			}
			byIndex[gm.index] = acc
			accelerators = append(accelerators, acc)
		}
		gm.apply(acc)
	}

	if len(accelerators) == 0 {
		return nil, fmt.Errorf("no metrics found")
	}

	return &spb.SystemMetricsRecord{
		Timestamp:    timestamppb.Now(),
		Accelerators: accelerators,
	}, nil
}

// Probe fetches the Nvidia GPU metadata from the endpoint and returns it as an EnvironmentRecord.
//
// A GPU is identified by its model name and UUID.
func (de *DCGMExporter) Probe(ctx context.Context) *spb.EnvironmentRecord {
	ctx, cancel := context.WithTimeout(ctx, DefaultOpenMetricsTimeout)
	defer cancel()

	gpuMetrics, err := de.gpuMetrics(ctx)
	if err != nil {
		return nil
	}

	var gpuNvidia []*spb.GpuNvidiaInfo
	for _, gm := range gpuMetrics {
		// GPU Model Name and UUID uniquely identify a GPU.
		// Do not store the information if either is missing.
		if gm.modelName == "" || gm.uuid == "" {
			continue
		}
		gpuNvidia = append(gpuNvidia, &spb.GpuNvidiaInfo{
			Name: gm.modelName,
			Uuid: gm.uuid,
		})
	}

	if len(gpuNvidia) == 0 {
		return nil
	}

	return &spb.EnvironmentRecord{
		GpuNvidia: gpuNvidia,
		GpuCount:  uint32(len(gpuNvidia)),
		GpuType:   gpuNvidia[0].Name, // TODO: handle multiple GPU types
	}
}
