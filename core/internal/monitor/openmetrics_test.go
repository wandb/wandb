package monitor_test

import (
	"fmt"
	"math/rand/v2"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
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
	client.HTTPClient.Timeout = 1 * time.Second
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
			_ = monitor.NewOpenMetrics(logger, "test", server.URL, nil /* filters */, nil /* headers */, retryClient)
		})
	}
}

func TestDCGM(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, err := w.Write([]byte(randomMetrics()))
		assert.NoError(t, err)
	}))
	defer server.Close()

	logger := observability.NewNoOpLogger()
	om := monitor.NewOpenMetrics(logger, "dcgm", server.URL, nil /* filters */, nil /* headers */, nil /* client */)

	result, err := om.Sample()
	assert.NoError(t, err)
	assert.NotEmpty(t, result)

	// Check if the keys in the result match the expected format
	for _, item := range result.Item {
		assert.Regexp(t, `^openmetrics\.dcgm\.(DCGM_FI_DEV_MEM_COPY_UTIL|DCGM_FI_DEV_GPU_TEMP|DCGM_FI_DEV_POWER_USAGE)\.\d+$`, item.Key)
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
					LabelFilters:    []monitor.LabelFilter{{"pod", "wandb-.*"}},
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
					LabelFilters:    []monitor.LabelFilter{{"pod", "^wandb-.*"}},
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
					LabelFilters:    []monitor.LabelFilter{{"pod", "wandb-.*"}},
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
					LabelFilters:    []monitor.LabelFilter{{"pod", "^wandb-.*"}},
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
					LabelFilters:    []monitor.LabelFilter{{"pod", "wandb-.*"}},
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
					LabelFilters:    []monitor.LabelFilter{{"pod", "wandb-.*"}},
				},
			},
			endpointName:  "node8",
			metricName:    "DCGM_FI_DEV_POWER_USAGE",
			metricLabels:  map[string]string{"pod": "wandb-1337"},
			shouldCapture: false,
		},
	}

	logger := observability.NewNoOpLogger()
	for i, tc := range testCases {
		t.Run(fmt.Sprintf("Case %d", i), func(t *testing.T) {
			om := monitor.NewOpenMetrics(logger, tc.endpointName, "http://localhost:9400", nil /* filters */, nil /* headers */, nil /* client */)
			om.SetFilters(tc.filters)
			result := om.ShouldCaptureMetric(tc.metricName, tc.metricLabels)
			assert.Equal(t, tc.shouldCapture, result)
		})
	}
}

func TestIntermittentFailure(t *testing.T) {
	var requestCount atomic.Int32

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		count := requestCount.Add(1)
		if count%2 == 0 {
			// Every other request fails
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		w.WriteHeader(http.StatusOK)
		_, err := w.Write([]byte(randomMetrics()))
		assert.NoError(t, err)
	}))
	defer server.Close()

	logger := observability.NewNoOpLogger()
	retryClient := newRetryableHTTPClient()
	retryClient.RetryMax = 1
	om := monitor.NewOpenMetrics(logger, "intermittent", server.URL, nil /* filters */, nil /* headers */, retryClient)

	// Run multiple samples to test intermittent behavior
	for i := range 2 {
		result, err := om.Sample()
		if err != nil {
			t.Logf("Sample %d failed: %v", i, err)
		} else {
			t.Logf("Sample %d succeeded with %d metrics", i, len(result.Item))
			assert.NotEmpty(t, result)
		}
	}

	// Verify that we made more requests than samples due to retries
	assert.Greater(t, requestCount.Load(), int32(2), "Expected more requests than samples due to retries")
}

func TestCache(t *testing.T) {
	logger := observability.NewNoOpLogger()
	om := monitor.NewOpenMetrics(logger, "dcgm", "http://localhost:9400", nil /* filters */, nil /* headers */, nil /* client */)

	filters := []monitor.Filter{
		{
			MetricNameRegex: ".*DCGM_FI_DEV_POWER_USAGE",
			LabelFilters:    []monitor.LabelFilter{{"pod", "wandb-.*"}},
		},
	}
	om.SetFilters(filters)
	metricName := "DCGM_FI_DEV_POWER_USAGE"
	metricLabels := map[string]string{"pod": "wandb-1337"}

	hash := monitor.GenerateLabelHash(metricLabels)
	// check that metricName+hash is not in the cache
	_, ok := om.Cache().Get(metricName + hash)
	assert.False(t, ok)

	om.ShouldCaptureMetric(metricName, metricLabels)
	// check that metricName+hash is in the cache
	_, ok = om.Cache().Get(metricName + hash)
	assert.True(t, ok)

	om.ShouldCaptureMetric(metricName, metricLabels)
	// check that metricName+hash is in the cache
	_, ok = om.Cache().Get(metricName + hash)
	assert.True(t, ok)
}

func TestOpenMetricsHeaders(t *testing.T) {
	var receivedToken string

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedToken = r.Header.Get("Authorization")
		w.WriteHeader(http.StatusOK)
		_, err := w.Write([]byte(randomMetrics()))
		assert.NoError(t, err)
	}))
	defer server.Close()

	logger := observability.NewNoOpLogger()
	headers := map[string]string{
		"Authorization": "Bearer test-token-123",
	}

	om := monitor.NewOpenMetrics(logger, "test", server.URL, nil /* filters */, headers, nil /* client */)

	result, err := om.Sample()
	assert.NoError(t, err)
	assert.NotEmpty(t, result)
	assert.Equal(t, "Bearer test-token-123", receivedToken, "Expected Authorization header to be sent with request")
}
