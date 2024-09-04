package monitor_test

import (
	"fmt"
	"math/rand/v2"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/pkg/monitor"
	"github.com/wandb/wandb/core/pkg/observability"
)

func randomInRange(vmin, vmax float64) float64 {
	return vmin + (vmax-vmin)*rand.Float64()
}

const fakeMetricsTemplate = `# HELP DCGM_FI_DEV_MEM_COPY_UTIL Memory utilization (in percent).
# TYPE DCGM_FI_DEV_MEM_COPY_UTIL gauge
DCGM_FI_DEV_MEM_COPY_UTIL{gpu="0",UUID="GPU-c601d117-58ff-cd30-ae20-529ab192ba51",device="nvidia0",modelName="Tesla T4",Hostname="gke-gke-dcgm-default-pool-eb7746d2-6vkd",container="",namespace="",pod=""} %f
DCGM_FI_DEV_MEM_COPY_UTIL{gpu="1",UUID="GPU-a7c8aa83-d112-b585-8456-5fc2f3e6d18e",device="nvidia1",modelName="Tesla T4",Hostname="gke-gke-dcgm-default-pool-eb7746d2-6vkd",container="dcgm-loadtest",namespace="default",pod="dcgm-loadtest"} %f
# HELP DCGM_FI_DEV_GPU_TEMP GPU temperature (in C)
# TYPE DCGM_FI_DEV_GPU_TEMP gauge
DCGM_FI_DEV_GPU_TEMP{gpu="0",UUID="GPU-c601d117-58ff-cd30-ae20-529ab192ba51",device="nvidia0",modelName="Tesla T4",Hostname="gke-gke-dcgm-default-pool-eb7746d2-6vkd",container="",namespace="",pod=""} %f
DCGM_FI_DEV_GPU_TEMP{gpu="1",UUID="GPU-a7c8aa83-d112-b585-8456-5fc2f3e6d18e",device="nvidia1",modelName="Tesla T4",Hostname="gke-gke-dcgm-default-pool-eb7746d2-6vkd",container="dcgm-loadtest",namespace="default",pod="dcgm-loadtest"} %f
# HELP DCGM_FI_DEV_POWER_USAGE Power draw (in W).
# TYPE DCGM_FI_DEV_POWER_USAGE gauge
DCGM_FI_DEV_POWER_USAGE{gpu="0",UUID="GPU-c601d117-58ff-cd30-ae20-529ab192ba51",device="nvidia0",modelName="Tesla T4",Hostname="gke-gke-dcgm-default-pool-eb7746d2-6vkd",container="",namespace="",pod=""} %f
DCGM_FI_DEV_POWER_USAGE{gpu="1",UUID="GPU-a7c8aa83-d112-b585-8456-5fc2f3e6d18e",device="nvidia1",modelName="Tesla T4",Hostname="gke-gke-dcgm-default-pool-eb7746d2-6vkd",container="dcgm-loadtest",namespace="default",pod="dcgm-loadtest"} %f
`

func randomMetrics() string {
	return fmt.Sprintf(fakeMetricsTemplate,
		randomInRange(0, 100),
		randomInRange(0, 100),
		randomInRange(0, 100),
		randomInRange(0, 100),
		randomInRange(0, 250),
		randomInRange(0, 250),
	)
}

func newRetryableHTTPClient() *retryablehttp.Client {
	client := retryablehttp.NewClient()
	client.RetryMax = 1
	client.HTTPClient.Timeout = 1
	return client
}

func TestDCGMNotAvailable(t *testing.T) {
	testCases := []struct {
		name       string
		statusCode int
		body       string
	}{
		{"Junk response", http.StatusOK, "CANNOTPARSETHISJUNK"},
		{"Retryable error", http.StatusTooManyRequests, ""},
		{"Non-retryable error", http.StatusNotFound, ""},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(tc.statusCode)
				_, err := w.Write([]byte(tc.body))
				assert.NoError(t, err)
			}))
			defer server.Close()

			logger := observability.NewNoOpLogger()
			retryClient := newRetryableHTTPClient()
			om := monitor.NewOpenMetrics(logger, "test", server.URL, nil, retryClient)
			assert.False(t, om.IsAvailable())
		})
	}
}
func TestEndpointHang(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Simulate a timeout by not responding
		select {}
	}))
	defer server.Close()

	logger := observability.NewNoOpLogger()
	retryClient := newRetryableHTTPClient()
	om := monitor.NewOpenMetrics(logger, "test", server.URL, nil, retryClient)
	assert.False(t, om.IsAvailable())
}

func TestDCGM(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, err := w.Write([]byte(randomMetrics()))
		assert.NoError(t, err)
	}))
	defer server.Close()

	logger := observability.NewNoOpLogger()
	om := monitor.NewOpenMetrics(logger, "dcgm", server.URL, nil, nil)

	assert.True(t, om.IsAvailable())

	result, err := om.Sample()
	assert.NoError(t, err)
	assert.NotEmpty(t, result)

	// Check if the keys in the result match the expected format
	for key := range result {
		assert.Regexp(t, `^openmetrics\.dcgm\.(DCGM_FI_DEV_MEM_COPY_UTIL|DCGM_FI_DEV_GPU_TEMP|DCGM_FI_DEV_POWER_USAGE)\.\d+$`, key)
	}
}

func TestMetricFilters(t *testing.T) {
	testCases := []struct {
		filters       []monitor.Filter
		endpointName  string
		metricName    string
		metricLabels  map[string]string
		shouldCapture bool
	}{
		{
			filters: []monitor.Filter{
				{
					MetricNameRegex: ".*DCGM_FI_DEV_POWER_USAGE",
					LabelFilters:    [][2]string{{"pod", "wandb-.*"}},
				},
			},
			endpointName:  "node1",
			metricName:    "DCGM_FI_DEV_POWER_USAGE",
			metricLabels:  map[string]string{"pod": "wandb-1337"},
			shouldCapture: true,
		},
		{
			filters: []monitor.Filter{
				{
					MetricNameRegex: ".*DCGM_FI_DEV_POWER_USAGE",
					LabelFilters:    [][2]string{{"pod", "^wandb-.*"}},
				},
			},
			endpointName:  "node2",
			metricName:    "DCGM_FI_DEV_POWER_USAGE",
			metricLabels:  map[string]string{"pod": "not-wandb-1337"},
			shouldCapture: false,
		},
		{
			filters: []monitor.Filter{
				{
					MetricNameRegex: ".*DCGM_.*",
				},
			},
			endpointName:  "node4",
			metricName:    "DCGM_FI_DEV_POWER_USAGE",
			metricLabels:  map[string]string{"pod": "wandb-1337", "container": "not-wandb"},
			shouldCapture: true,
		},
		{
			filters: []monitor.Filter{
				{
					MetricNameRegex: ".*",
				},
			},
			endpointName:  "node5",
			metricName:    "DCGM_FI_DEV_POWER_USAGE",
			metricLabels:  map[string]string{"pod": "wandb-1337", "container": "not-wandb"},
			shouldCapture: true,
		},
		{
			filters: []monitor.Filter{
				{
					MetricNameRegex: ".*DCGM_.*",
					LabelFilters:    [][2]string{{"pod", "wandb-.*"}},
				},
			},
			endpointName:  "node6",
			metricName:    "DCGM_FI_DEV_POWER_USAGE",
			metricLabels:  map[string]string{"pod": "wandb-1337"},
			shouldCapture: true,
		},
		{
			filters: []monitor.Filter{
				{
					MetricNameRegex: ".*DCGM_.*",
					LabelFilters:    [][2]string{{"pod", "^wandb-.*"}},
				},
			},
			endpointName:  "node7",
			metricName:    "DCGM_FI_DEV_POWER_USAGE",
			metricLabels:  map[string]string{"pod": "not-wandb-1337"},
			shouldCapture: false,
		},
		{
			filters: []monitor.Filter{
				{
					MetricNameRegex: "node[0-9].DCGM_.*",
					LabelFilters:    [][2]string{{"pod", "wandb-.*"}},
				},
			},
			endpointName:  "node8",
			metricName:    "DCGM_FI_DEV_POWER_USAGE",
			metricLabels:  map[string]string{"pod": "wandb-1337"},
			shouldCapture: true,
		},
		{
			filters: []monitor.Filter{
				{
					MetricNameRegex: "node[0-7].DCGM_.*",
					LabelFilters:    [][2]string{{"pod", "wandb-.*"}},
				},
			},
			endpointName:  "node8",
			metricName:    "DCGM_FI_DEV_POWER_USAGE",
			metricLabels:  map[string]string{"pod": "wandb-1337"},
			shouldCapture: false,
		},
	}

	for i, tc := range testCases {
		t.Run(fmt.Sprintf("Case %d", i), func(t *testing.T) {
			result := monitor.ShouldCaptureMetric(
				tc.endpointName,
				tc.metricName,
				tc.metricLabels,
				tc.filters,
			)
			assert.Equal(t, tc.shouldCapture, result)
		})
	}
}
