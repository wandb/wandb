package api

import (
	"net/http"
	"testing"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
)

type MockRetryableHTTPClient struct {
}

func (m *MockRetryableHTTPClient) Do(req *retryablehttp.Request) (*http.Response, error) {
	return nil, nil
}

func TestSend_NoResponse(t *testing.T) {
	mockRetryableHTTPClient := new(MockRetryableHTTPClient)

	client := &clientImpl{
		retryableHTTP: mockRetryableHTTPClient,
	}
	req, _ := retryablehttp.NewRequest("GET", "http://example.com", nil)
	resp, err := client.send(req)

	// An error should be returned indicating that no response was received.
	assert.Nil(t, resp)
	assert.NotNil(t, err)
	assert.EqualError(t, err, "api: no response")
}
