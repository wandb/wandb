package remote

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// mockFileContent is used as test file content
var mockFileContent = []byte(
	"This is a test file with some content for testing HTTP range requests. " +
		"It should be long enough to test various read operations.",
)

// Helper function to create a test HTTP server
// that serves a file with range support
func createTestServer(t *testing.T) *httptest.Server {
	t.Helper()

	return httptest.NewServer(http.HandlerFunc(func(
		respWriter http.ResponseWriter,
		req *http.Request,
	) {
		switch req.Method {
		case http.MethodHead:
			respWriter.Header().Set(
				"Content-Length",
				strconv.Itoa(len(mockFileContent)),
			)
			respWriter.WriteHeader(http.StatusOK)

		case http.MethodGet:
			rangeHeader := req.Header.Get("Range")

			// Return full content if no range specified
			if rangeHeader == "" {
				respWriter.Header().Set(
					"Content-Length",
					strconv.Itoa(len(mockFileContent)),
				)
				respWriter.WriteHeader(http.StatusOK)
				_, err := respWriter.Write(mockFileContent)
				require.NoError(t, err)

				return
			}

			if !strings.HasPrefix(rangeHeader, "bytes=") {
				respWriter.WriteHeader(http.StatusBadRequest)
				return
			}

			rangeStr := strings.TrimPrefix(rangeHeader, "bytes=")
			parts := strings.Split(rangeStr, "-")
			if len(parts) != 2 {
				respWriter.WriteHeader(http.StatusBadRequest)
				return
			}

			start, err := strconv.ParseInt(parts[0], 10, 64)
			if err != nil {
				respWriter.WriteHeader(http.StatusBadRequest)
				return
			}

			end, err := strconv.ParseInt(parts[1], 10, 64)
			if err != nil {
				respWriter.WriteHeader(http.StatusBadRequest)
				return
			}

			// Validate range
			if start < 0 || end > int64(len(mockFileContent)) || start > end {
				respWriter.WriteHeader(http.StatusRequestedRangeNotSatisfiable)
				return
			}

			// Return partial content
			respWriter.Header().Set(
				"Content-Range",
				fmt.Sprintf(
					"bytes %d-%d/%d",
					start,
					end-1,
					len(mockFileContent),
				),
			)
			respWriter.Header().Set(
				"Content-Length",
				strconv.FormatInt(end-start, 10),
			)
			respWriter.WriteHeader(http.StatusPartialContent)
			_, err = respWriter.Write(mockFileContent[start:end])
			require.NoError(t, err)

		default:
			respWriter.WriteHeader(http.StatusMethodNotAllowed)
		}
	}))
}

func createErrorServer(t *testing.T, statusCode int) *httptest.Server {
	t.Helper()

	return httptest.NewServer(http.HandlerFunc(func(
		respWriter http.ResponseWriter,
		req *http.Request,
	) {
		// Don't set Content-Length for error responses
		respWriter.WriteHeader(statusCode)
		// Don't write any body for HEAD requests
		if req.Method != http.MethodHead {
			_, err := respWriter.Write([]byte("error"))
			require.NoError(t, err)
		}
	}))
}

// Test server with no Content-Length header
func createNoContentLengthServer(t *testing.T) *httptest.Server {
	t.Helper()

	return httptest.NewServer(http.HandlerFunc(func(
		respWriter http.ResponseWriter,
		req *http.Request,
	) {
		if req.Method == http.MethodHead {
			respWriter.WriteHeader(http.StatusOK)
		}
	}))
}

func TestGetObjectSize(t *testing.T) {
	ctx := context.Background()
	client := retryablehttp.NewClient()
	client.HTTPClient.Timeout = 1 * time.Second
	client.RetryMax = 1
	client.RetryWaitMin = 1 * time.Millisecond
	client.RetryWaitMax = 10 * time.Millisecond

	t.Run("successful HEAD request", func(t *testing.T) {
		server := createTestServer(t)
		defer server.Close()

		size, err := getObjectSize(ctx, client, server.URL)
		assert.NoError(t, err)

		expectedSize := int64(len(mockFileContent))
		assert.Equal(t, expectedSize, size)
	})

	t.Run("HEAD request with no Content-Length", func(t *testing.T) {
		server := createNoContentLengthServer(t)
		defer server.Close()

		size, err := getObjectSize(ctx, client, server.URL)
		assert.Error(t, err)

		// When Content-Length is not set, it should return -1
		assert.Equal(t, int64(-1), size)
	})

	t.Run("server returns error", func(t *testing.T) {
		server := createErrorServer(t, http.StatusInternalServerError)
		defer server.Close()

		size, err := getObjectSize(ctx, client, server.URL)
		assert.Error(t, err)
		assert.Contains(
			t,
			err.Error(),
			"giving up after 2 attempt(s)",
		)

		// When server returns error status without Content-Length, it should return -1
		assert.Equal(t, int64(-1), size)
	})

	t.Run("invalid URL", func(t *testing.T) {
		size, err := getObjectSize(ctx, client, "http://invalidurl/invalid")

		assert.Error(t, err)
		assert.Equal(t, int64(-1), size)
	})

	t.Run("context cancellation", func(t *testing.T) {
		server := createTestServer(t)
		defer server.Close()

		cancelCtx, cancel := context.WithCancel(ctx)
		cancel() // Cancel immediately

		size, err := getObjectSize(cancelCtx, client, server.URL)

		assert.Error(t, err)
		assert.Contains(
			t,
			err.Error(),
			"context canceled",
		)
		assert.Equal(t, int64(-1), size)
	})
}

func TestNewHttpFileReader(t *testing.T) {
	ctx := context.Background()
	client := retryablehttp.NewClient()
	client.HTTPClient.Timeout = 10 * time.Second

	t.Run("successful creation", func(t *testing.T) {
		server := createTestServer(t)
		defer server.Close()

		reader, err := NewHttpFileReader(ctx, client, server.URL)
		require.NoError(t, err)

		httpReader, ok := reader.(*HttpFileReader)
		assert.True(t, ok)
		assert.Equal(t, int64(0), httpReader.offset)
		assert.Equal(t, server.URL, httpReader.url)

		expectedSize := int64(len(mockFileContent))
		assert.Equal(t, expectedSize, httpReader.fileSize)

		assert.Equal(t, int64(0), httpReader.offset)
		assert.Equal(t, server.URL, httpReader.url)
	})

	t.Run("failed to get file size", func(t *testing.T) {
		_, err := NewHttpFileReader(ctx, client, "http://invalidurl/invalid")
		assert.Error(t, err)
	})
}

func TestHttpFileReader_ReadAt(t *testing.T) {
	ctx := context.Background()
	client := retryablehttp.NewClient()
	client.HTTPClient.Timeout = 10 * time.Second
	server := createTestServer(t)
	defer server.Close()

	reader, err := NewHttpFileReader(ctx, client, server.URL)
	require.NoError(t, err)

	t.Run("read entire file", func(t *testing.T) {
		buffer := make([]byte, reader.(*HttpFileReader).fileSize)

		n, err := reader.ReadAt(buffer, 0)

		require.NoError(t, err)
		assert.Equal(t, len(mockFileContent), n)
		assert.Equal(t, mockFileContent, buffer)
		assert.Equal(t, mockFileContent, buffer)
	})

	t.Run("read partial content from middle", func(t *testing.T) {
		length := 20
		buffer := make([]byte, length)
		offset := int64(10)

		n, err := reader.ReadAt(buffer, offset)

		assert.NoError(t, err)
		assert.Equal(t, length, n)

		expectedData := mockFileContent[offset : offset+int64(length)]
		assert.Equal(t, expectedData, buffer)

	})

	t.Run("read with negative offset", func(t *testing.T) {
		buffer := make([]byte, 10)
		_, err = reader.ReadAt(buffer, -1)

		assert.Error(t, err)
		assert.Contains(
			t,
			err.Error(),
			"negative offset",
		)
	})

	t.Run("read beyond file size", func(t *testing.T) {
		offset := int64(len(mockFileContent) - 5)
		buffer := make([]byte, 10)
		n, err := reader.ReadAt(buffer, offset)

		assert.Error(t, err)
		assert.Equal(t, io.EOF, err)
		assert.Equal(t, 5, n)
	})
}

func TestHttpFileReader_Seek(t *testing.T) {
	ctx := context.Background()
	client := retryablehttp.NewClient()
	client.HTTPClient.Timeout = 10 * time.Second
	server := createTestServer(t)
	defer server.Close()

	reader, err := NewHttpFileReader(ctx, client, server.URL)
	require.NoError(t, err)

	httpReader := reader.(*HttpFileReader)

	t.Run("seek from start", func(t *testing.T) {
		newOffset := int64(50)
		pos, err := httpReader.Seek(newOffset, io.SeekStart)

		assert.NoError(t, err)
		assert.Equal(t, newOffset, pos)
		assert.Equal(t, newOffset, httpReader.offset)
	})

	t.Run("seek from current", func(t *testing.T) {
		// Set initial position
		httpReader.offset = 30

		seekOffset := int64(20)
		pos, err := httpReader.Seek(seekOffset, io.SeekCurrent)

		assert.NoError(t, err)

		expectedPos := int64(50)
		assert.Equal(t, expectedPos, pos)
		assert.Equal(t, expectedPos, httpReader.offset)
	})

	t.Run("seek from current with negative offset", func(t *testing.T) {
		// Set initial position
		httpReader.offset = 30

		seekOffset := int64(-10)
		pos, err := httpReader.Seek(seekOffset, io.SeekCurrent)

		assert.NoError(t, err)

		expectedPos := int64(20)
		assert.Equal(t, expectedPos, pos)
		assert.Equal(t, expectedPos, httpReader.offset)
	})

	t.Run("seek from end", func(t *testing.T) {
		seekOffset := int64(-10)

		pos, err := httpReader.Seek(seekOffset, io.SeekEnd)

		assert.NoError(t, err)

		expectedPos := httpReader.fileSize - 10
		assert.Equal(t, expectedPos, pos)
		assert.Equal(t, expectedPos, httpReader.offset)
	})

	t.Run("seek with invalid whence", func(t *testing.T) {
		invalidWhence := 999
		_, err := httpReader.Seek(10, invalidWhence)

		assert.Error(t, err)
		assert.Contains(
			t,
			err.Error(),
			"invalid whence",
		)
	})

	t.Run("seek beyond file boundaries", func(t *testing.T) {
		// Seek beyond file size
		pos, err := httpReader.Seek(httpReader.fileSize+1, io.SeekStart)
		assert.Error(t, err)
		assert.Contains(
			t,
			err.Error(),
			"offset exceeds file size",
		)
		assert.Equal(t, int64(-1), pos)

		// Seek before start of file
		pos, err = httpReader.Seek(-1, io.SeekStart)
		assert.Error(t, err)
		assert.Contains(
			t,
			err.Error(),
			"offset start before file",
		)
		assert.Equal(t, int64(-1), pos)
	})
}

func TestHttpFileReader_ServerErrors(t *testing.T) {
	ctx := context.Background()
	client := retryablehttp.NewClient()
	client.HTTPClient.Timeout = 5 * time.Second
	client.RetryMax = 2
	client.RetryWaitMin = 1 * time.Millisecond
	client.RetryWaitMax = 10 * time.Millisecond

	t.Run("server returns error on range request", func(t *testing.T) {
		// Create a server that returns errors for GET requests
		server := httptest.NewServer(http.HandlerFunc(func(
			responseWriter http.ResponseWriter,
			request *http.Request,
		) {
			switch request.Method {
			case http.MethodHead:
				responseWriter.Header().Set("Content-Length", strconv.Itoa(len(mockFileContent)))
				responseWriter.WriteHeader(http.StatusOK)
			default:
				responseWriter.WriteHeader(http.StatusInternalServerError)
			}
		}))
		defer server.Close()

		reader, err := NewHttpFileReader(ctx, client, server.URL)
		require.NoError(t, err)

		buffer := make([]byte, 10)
		n, err := reader.ReadAt(buffer, 0)

		// Should get an EOF or unexpected EOF error due to server error
		assert.Error(t, err)
		assert.Contains(
			t,
			err.Error(),
			"giving up after 3 attempt(s)",
		)
		assert.Equal(t, 0, n)
	})

	t.Run("context timeout during read", func(t *testing.T) {
		// Create a slow server that delays longer than the context timeout
		server := httptest.NewServer(http.HandlerFunc(func(
			responseWriter http.ResponseWriter,
			request *http.Request,
		) {
			switch request.Method {
			case http.MethodHead:
				responseWriter.Header().Set("Content-Length", strconv.Itoa(len(mockFileContent)))
				responseWriter.WriteHeader(http.StatusOK)
			default:
				// Sleep longer than the context timeout to ensure context cancellation
				time.Sleep(500 * time.Millisecond)
				responseWriter.WriteHeader(http.StatusOK)
				_, err := responseWriter.Write(mockFileContent)
				require.NoError(t, err)
			}
		}))
		defer server.Close()

		// Create a client with retries disabled for this test
		testClient := retryablehttp.NewClient()
		testClient.HTTPClient.Timeout = 10 * time.Second
		testClient.RetryMax = 0 // Disable retries to test context timeout directly

		// Create reader with short timeout context
		timeoutCtx, cancel := context.WithTimeout(ctx, 100*time.Millisecond)
		defer cancel()

		reader, err := NewHttpFileReader(timeoutCtx, testClient, server.URL)
		require.NoError(t, err)

		buffer := make([]byte, 10)
		_, err = reader.ReadAt(buffer, 0)

		assert.Error(t, err)
		assert.Contains(
			t,
			err.Error(),
			"context deadline exceeded",
		)
	})
}
