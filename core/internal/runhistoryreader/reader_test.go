package runhistoryreader

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/gqlmock"
)

// mockRoundTripper is a mock implementation of http.RoundTripper for testing
type mockRoundTripper struct {
	responseBody   []byte
	responseStatus int
	capturedURL    string
}

func (m *mockRoundTripper) RoundTrip(req *http.Request) (*http.Response, error) {
	// Capture the request URL for verification
	m.capturedURL = req.URL.String()

	// Return mock response
	return &http.Response{
		StatusCode: m.responseStatus,
		Body:       io.NopCloser(bytes.NewReader(m.responseBody)),
		Header:     make(http.Header),
	}, nil
}

func TestHistoryReader_GetHistorySteps(t *testing.T) {
	reader := New(
		"test-entity",
		"test-project",
		"test-run-id",
		gqlmock.NewMockClient(),
		http.DefaultClient,
	)

	err := reader.GetHistorySteps([]string{"metric1"}, 0, 10)
	assert.Error(t, err)
}

func TestHistoryReader_GetSignedUrls(t *testing.T) {
	expectedUrls := []string{"https://example.com/metric1.parquet"}
	expectedUrlsJsonBytes, _ := json.Marshal(expectedUrls)
	expectedUrlsJsonString := string(expectedUrlsJsonBytes)

	fmt.Println(expectedUrlsJsonString)
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunParquetHistory"),
		`{
			"project": {
				"run": {
					"parquetHistory": {
						"parquetUrls": `+expectedUrlsJsonString+`
					}
				}
			}
		}`,
	)
	reader := New(
		"test-entity",
		"test-project",
		"test-run-id",
		mockGQL,
		http.DefaultClient,
	)

	urls, err := reader.getRunHistoryFileUrls()

	assert.NoError(t, err)
	assert.Len(t, urls, 1)
	assert.Equal(t, urls[0], expectedUrls[0])
}

func TestHistoryReader_DownloadRunHistoryFile(t *testing.T) {
	tempDir := t.TempDir()
	downloadDir := filepath.Join(tempDir, "downloads")
	expectedFileName := "test-run.parquet"
	expectedURL := "https://example.com/" + expectedFileName
	expectedContent := []byte("test parquet file content")
	mockTransport := &mockRoundTripper{
		responseBody:   expectedContent,
		responseStatus: http.StatusOK,
	}
	mockHTTPClient := &http.Client{
		Transport: mockTransport,
	}
	reader := New(
		"test-entity",
		"test-project",
		"test-run-id",
		gqlmock.NewMockClient(),
		mockHTTPClient,
	)

	err := reader.downloadRunHistoryFile(
		expectedURL,
		downloadDir,
		expectedFileName,
	)

	assert.NoError(t, err)
	downloadedFilePath := filepath.Join(downloadDir, expectedFileName)
	assert.FileExists(t, downloadedFilePath)

	content, err := os.ReadFile(downloadedFilePath)
	assert.NoError(t, err)
	assert.Equal(t, expectedContent, content)
	assert.Equal(t, mockTransport.capturedURL, expectedURL)
}
