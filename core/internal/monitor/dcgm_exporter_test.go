package monitor_test

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestParsePromQLURL(t *testing.T) {
	tests := []struct {
		name          string
		url           string
		wantBaseURL   string
		wantQueries   []string
		wantErr       bool
		wantErrPrefix string
	}{
		{
			name:        "valid URL with single query",
			url:         "http://localhost:9090/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP",
			wantBaseURL: "http://localhost:9090",
			wantQueries: []string{"DCGM_FI_DEV_GPU_TEMP"},
			wantErr:     false,
		},
		{
			name:        "valid URL with multiple queries",
			url:         "http://localhost:9090/api/v1/query?query=query1&query=query2",
			wantBaseURL: "http://localhost:9090",
			wantQueries: []string{"query1", "query2"},
			wantErr:     false,
		},
		{
			name:          "invalid URL format",
			url:           "://invalid-url",
			wantErr:       true,
			wantErrPrefix: "parse",
		},
		{
			name:          "missing query parameter",
			url:           "http://localhost:9090/api/v1/query",
			wantErr:       true,
			wantErrPrefix: "no query parameter provided",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			baseURL, queries, err := monitor.ParsePromQLURL(tt.url)
			if tt.wantErr {
				require.Error(t, err)
				if tt.wantErrPrefix != "" {
					assert.Contains(t, err.Error(), tt.wantErrPrefix)
				}
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.wantBaseURL, baseURL)
			assert.Equal(t, tt.wantQueries, queries)
		})
	}
}

func TestNewDCGMExporter(t *testing.T) {
	logger := observability.NewNoOpLogger()

	tests := []struct {
		name        string
		params      monitor.DCGMExporterParams
		wantNil     bool
		wantQueries []string
	}{
		{
			name: "valid prometheus URL",
			params: monitor.DCGMExporterParams{
				URL:    "http://localhost:9090/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP",
				Logger: logger,
			},
			wantNil:     false,
			wantQueries: []string{"DCGM_FI_DEV_GPU_TEMP"},
		},
		{
			name: "invalid URL",
			params: monitor.DCGMExporterParams{
				URL:    "://invalid-url",
				Logger: logger,
			},
			wantNil: true,
		},
		{
			name: "metrics endpoint",
			params: monitor.DCGMExporterParams{
				URL:    "http://localhost:9090/metrics",
				Logger: logger,
			},
			wantNil: true, // Currently returns nil as /metrics not implemented
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			exporter := monitor.NewDCGMExporter(tt.params)
			if tt.wantNil {
				assert.Nil(t, exporter)
				return
			}
			require.NotNil(t, exporter)
			assert.Equal(t, tt.wantQueries, exporter.Queries())
		})
	}
}

func TestSample(t *testing.T) {
	// Create a mock server that returns our fake data
	fakeResponse := map[string]interface{}{
		"status": "success",
		"data": map[string]interface{}{
			"resultType": "vector",
			"result": []map[string]interface{}{
				{
					"metric": map[string]string{
						"__name__":  "DCGM_FI_DEV_GPU_TEMP",
						"gpu":       "0",
						"modelName": "NVIDIA H100 80GB HBM3",
						"uuid":      "GPU-xxx",
						"hostname":  "node1",
					},
					"value": []interface{}{float64(1738025769), "23"},
				},
			},
		},
	}

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		err := json.NewEncoder(w).Encode(fakeResponse)
		require.NoError(t, err, "Failed to encode JSON response")
	}))
	defer server.Close()

	logger := observability.NewNoOpLogger()
	client := retryablehttp.NewClient()
	client.HTTPClient.Timeout = time.Second * 5

	exporter := monitor.NewDCGMExporter(monitor.DCGMExporterParams{
		URL:    server.URL + "/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP",
		Logger: logger,
		Client: client,
	})
	require.NotNil(t, exporter)

	record, err := exporter.Sample()
	require.NoError(t, err)
	require.NotNil(t, record)

	fmt.Println(record)

	// Check if the temperature metric was correctly mapped
	temp := record.Item[0]
	assert.Equal(t, "gpu.0.temp/l:node1", temp.Key)
	assert.Equal(t, "23", temp.ValueJson)
}

func TestProbe(t *testing.T) {
	// Create mock data for two GPUs
	mockResponse := map[string]interface{}{
		"status": "success",
		"data": map[string]interface{}{
			"resultType": "vector",
			"result": []map[string]interface{}{
				{
					"metric": map[string]string{
						"__name__":  "DCGM_FI_DEV_GPU_TEMP",
						"gpu":       "0",
						"modelName": "NVIDIA H100 80GB HBM3",
						"uuid":      "GPU-4a0cba69-b441-dbd3-2f36-9fab5a5a92a7",
						"hostname":  "node1",
						"node":      "node1",
					},
					"value": []interface{}{float64(1738025769), "23"},
				},
				{
					"metric": map[string]string{
						"__name__":  "DCGM_FI_DEV_GPU_TEMP",
						"gpu":       "1",
						"modelName": "NVIDIA H100 80GB HBM3",
						"uuid":      "GPU-690ff1ad-ea73-493a-c901-69609a679e30",
						"hostname":  "node1",
						"node":      "node1",
					},
					"value": []interface{}{float64(1738025769), "24"},
				},
			},
		},
	}

	// Set up test server
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Verify the incoming request
		assert.Equal(t, "/api/v1/query", r.URL.Path)
		w.Header().Set("Content-Type", "application/json")
		err := json.NewEncoder(w).Encode(mockResponse)
		require.NoError(t, err, "Failed to encode JSON response")
	}))
	defer server.Close()

	// Create exporter with test configuration
	logger := observability.NewNoOpLogger()
	client := retryablehttp.NewClient()
	client.HTTPClient.Timeout = time.Second * 5

	exporter := monitor.NewDCGMExporter(monitor.DCGMExporterParams{
		URL:    server.URL + "/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP",
		Logger: logger,
		Client: client,
	})
	require.NotNil(t, exporter)

	// Get metadata from Probe method
	metadata := exporter.Probe(context.Background())
	require.NotNil(t, metadata, "Probe should return non-nil metadata")

	// Verify basic metadata
	assert.Equal(t, uint32(2), metadata.GpuCount, "Should detect exactly 2 GPUs")
	assert.Equal(t, "NVIDIA H100 80GB HBM3", metadata.GpuType, "Should correctly identify GPU type")

	// Verify GPU-specific information
	require.Len(t, metadata.GpuNvidia, 2, "Should return info for both GPUs")

	// Create map of UUID to GPU info for easier testing
	gpuMap := make(map[string]*spb.GpuNvidiaInfo)
	for _, gpu := range metadata.GpuNvidia {
		gpuMap[gpu.Uuid] = gpu
	}

	// Test first GPU
	gpu1 := gpuMap["GPU-4a0cba69-b441-dbd3-2f36-9fab5a5a92a7"]
	require.NotNil(t, gpu1, "First GPU should be present")
	assert.Equal(t, "NVIDIA H100 80GB HBM3", gpu1.Name)

	// Test second GPU
	gpu2 := gpuMap["GPU-690ff1ad-ea73-493a-c901-69609a679e30"]
	require.NotNil(t, gpu2, "Second GPU should be present")
	assert.Equal(t, "NVIDIA H100 80GB HBM3", gpu2.Name)

	// Test edge cases
	t.Run("missing model name", func(t *testing.T) {
		// Modify response to omit modelName
		modifiedResponse := mockResponse
		result := modifiedResponse["data"].(map[string]interface{})["result"].([]map[string]interface{})
		delete(result[0]["metric"].(map[string]string), "modelName")

		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			err := json.NewEncoder(w).Encode(modifiedResponse)
			require.NoError(t, err, "Failed to encode JSON response")
		}))
		defer server.Close()

		exporter := monitor.NewDCGMExporter(monitor.DCGMExporterParams{
			URL:    server.URL + "/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP",
			Logger: logger,
			Client: client,
		})

		metadata := exporter.Probe(context.Background())
		require.NotNil(t, metadata)
		assert.Equal(t, uint32(1), metadata.GpuCount, "Should only detect GPU with complete information")
	})

	t.Run("missing uuid", func(t *testing.T) {
		// Modify response to omit UUID
		modifiedResponse := mockResponse
		result := modifiedResponse["data"].(map[string]interface{})["result"].([]map[string]interface{})
		delete(result[0]["metric"].(map[string]string), "uuid")

		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			err := json.NewEncoder(w).Encode(modifiedResponse)
			require.NoError(t, err, "Failed to encode JSON response")
		}))
		defer server.Close()

		exporter := monitor.NewDCGMExporter(monitor.DCGMExporterParams{
			URL:    server.URL + "/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP",
			Logger: logger,
			Client: client,
		})

		metadata := exporter.Probe(context.Background())
		require.NotNil(t, metadata)
		assert.Equal(t, uint32(1), metadata.GpuCount, "Should only detect GPU with complete information")
	})
}

func TestDCGMExporterAuth(t *testing.T) {
	var receivedToken string

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedToken = r.Header.Get("Authorization")

		// Return a minimal valid response
		response := map[string]interface{}{
			"status": "success",
			"data": map[string]interface{}{
				"resultType": "vector",
				"result": []map[string]interface{}{
					{
						"metric": map[string]string{
							"__name__":  "DCGM_FI_DEV_GPU_TEMP",
							"gpu":       "0",
							"modelName": "NVIDIA H100 80GB HBM3",
							"uuid":      "GPU-xxx",
						},
						"value": []interface{}{float64(1738025769), "23"},
					},
				},
			},
		}
		err := json.NewEncoder(w).Encode(response)
		require.NoError(t, err, "Failed to encode JSON response")
	}))
	defer server.Close()

	logger := observability.NewNoOpLogger()
	headers := map[string]string{
		"Authorization": "Bearer test-token-123",
	}

	exporter := monitor.NewDCGMExporter(monitor.DCGMExporterParams{
		URL:     server.URL + "/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP",
		Headers: headers,
		Logger:  logger,
	})

	// Make a request using Sample() to trigger the HTTP call
	result, err := exporter.Sample()
	assert.NoError(t, err)
	assert.NotNil(t, result)
	assert.Equal(t, "Bearer test-token-123", receivedToken, "Expected Authorization header to be sent with request")
}
