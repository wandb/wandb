package wbapi_test

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"strings"
	"testing"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/wbapi"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// fakeRetryableClient records the request it receives and returns a canned
// response.
type fakeRetryableClient struct {
	resp    *http.Response
	err     error
	called  bool
	gotReq  *retryablehttp.Request
	gotBody []byte
}

func (c *fakeRetryableClient) Do(req *retryablehttp.Request) (*http.Response, error) {
	c.called = true
	c.gotReq = req
	c.gotBody, _ = req.BodyBytes()
	return c.resp, c.err
}

func okResponse() *http.Response {
	return &http.Response{
		StatusCode: http.StatusOK,
		Body:       io.NopCloser(strings.NewReader("{}")),
	}
}

func TestMarkRunFilesUploadedPostsUploadedFiles(t *testing.T) {
	baseURL, _ := url.Parse("https://api.example.test")
	client := &fakeRetryableClient{resp: okResponse()}
	handler := wbapi.NewFileStreamHandler(client, baseURL)

	response := handler.HandleMarkRunFilesUploaded(
		context.Background(),
		&spb.MarkRunFilesUploadedRequest{
			Entity:  "test-entity",
			Project: "test-project",
			RunId:   "test-run",
			Files:   []string{"a.txt", "b.txt"},
		},
	)

	require.NotNil(t, response.GetMarkRunFilesUploadedResponse())
	require.True(t, client.called)
	assert.Equal(t, http.MethodPost, client.gotReq.Method)
	assert.Equal(t,
		"https://api.example.test/files/test-entity/test-project/test-run/file_stream",
		client.gotReq.URL.String(),
	)
	assert.Equal(t, "application/json", client.gotReq.Header.Get("Content-Type"))

	var body map[string]any
	require.NoError(t, json.Unmarshal(client.gotBody, &body))
	assert.Equal(t, []any{"a.txt", "b.txt"}, body["uploaded"])
	// Only the "uploaded" field is sent; no run-state fields.
	assert.NotContains(t, body, "complete")
	assert.NotContains(t, body, "files")
}

func TestMarkRunFilesUploadedReturnsHTTPError(t *testing.T) {
	baseURL, _ := url.Parse("https://api.example.test")
	client := &fakeRetryableClient{
		resp: &http.Response{
			StatusCode: http.StatusForbidden,
			Status:     "403 Forbidden",
			Body:       io.NopCloser(strings.NewReader("nope")),
		},
	}
	handler := wbapi.NewFileStreamHandler(client, baseURL)

	response := handler.HandleMarkRunFilesUploaded(
		context.Background(),
		&spb.MarkRunFilesUploadedRequest{
			Entity:  "test-entity",
			Project: "test-project",
			RunId:   "test-run",
			Files:   []string{"a.txt"},
		},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Equal(t, int32(http.StatusForbidden), apiError.GetHttpStatus())
	assert.Contains(t, apiError.GetMessage(), "403 Forbidden")
}

func TestMarkRunFilesUploadedNoFilesSkipsRequest(t *testing.T) {
	baseURL, _ := url.Parse("https://api.example.test")
	client := &fakeRetryableClient{resp: okResponse()}
	handler := wbapi.NewFileStreamHandler(client, baseURL)

	response := handler.HandleMarkRunFilesUploaded(
		context.Background(),
		&spb.MarkRunFilesUploadedRequest{
			Entity:  "test-entity",
			Project: "test-project",
			RunId:   "test-run",
		},
	)

	require.NotNil(t, response.GetMarkRunFilesUploadedResponse())
	assert.False(t, client.called)
}
