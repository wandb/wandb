//go:build cloud_http

package tensorboard

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observabilitytest"
)

const wireEventKey = "run/events.out.tfevents.1.host"

// These tests exercise the production path from a cloud log URL through
// credentials and HTTP transport all the way to decoded TensorBoard events.
func TestCloudTensorBoardHTTPProviders(t *testing.T) {
	for _, scheme := range []string{"s3", "gs", "az"} {
		t.Run(scheme, func(t *testing.T) {
			fixture := &cloudWireFixture{
				t:          t,
				scheme:     scheme,
				data:       cloudEventBytes(1),
				generation: 1,
			}
			server := httptest.NewServer(http.HandlerFunc(fixture.serveHTTP))
			defer server.Close()
			configureCloudWireEnvironment(t, scheme, server.URL)
			cloudURL := scheme + "://bucket/run"
			if scheme == "az" {
				cloudURL = "az://test/bucket/run"
			}
			path, err := ParseTBPath(cloudURL)
			require.NoError(t, err)
			reader := NewTFEventReader(
				path,
				TFEventsFileFilter{},
				observabilitytest.NewTestLogger(t),
				time.Now,
			)
			defer reader.Close()
			requireNextCloudStep(t, reader, 1)
			requireNoCloudEvent(t, reader)

			first, second := cloudEventBytes(1), cloudEventBytes(2)
			fixture.replace(slices.Concat(first, second[:10]))
			requireNoCloudEvent(t, reader)
			fixture.replace(slices.Concat(first, second))
			requireNextCloudStep(t, reader, 2)

			fixture.mu.Lock()
			defer fixture.mu.Unlock()
			require.Contains(t, fixture.offsets, int64(len(first)))
			require.Contains(t, fixture.offsets, int64(len(first)+10))
			require.Greater(t, fixture.listRequests, 0)
		})
	}
}

func TestCloudTensorBoardGzipTailing(t *testing.T) {
	for _, scheme := range []string{"gs", "az"} {
		t.Run(scheme, func(t *testing.T) {
			fixture := &cloudWireFixture{t: t, scheme: scheme, gzip: true}
			first, second := cloudEventBytes(1), cloudEventBytes(2)
			fixture.replace(first)
			server := httptest.NewServer(http.HandlerFunc(fixture.serveHTTP))
			defer server.Close()
			configureCloudWireEnvironment(t, scheme, server.URL)
			cloudURL := scheme + "://bucket/run"
			if scheme == "az" {
				cloudURL = "az://test/bucket/run"
			}
			path, err := ParseTBPath(cloudURL)
			require.NoError(t, err)
			reader := NewTFEventReader(
				path,
				TFEventsFileFilter{},
				observabilitytest.NewTestLogger(t),
				time.Now,
			)
			defer reader.Close()
			requireNextCloudStep(t, reader, 1)
			requireNoCloudEvent(t, reader)
			fixture.replace(slices.Concat(first, second[:10]))
			requireNoCloudEvent(t, reader)
			fixture.replace(slices.Concat(first, second))
			requireNextCloudStep(t, reader, 2)
			fixture.mu.Lock()
			defer fixture.mu.Unlock()
			for _, offset := range fixture.offsets {
				require.Zero(t, offset, "gzip must be decoded from its start before seeking")
			}
		})
	}
}

func configureCloudWireEnvironment(t *testing.T, scheme, endpoint string) {
	t.Helper()
	switch scheme {
	case "s3":
		t.Setenv("AWS_ACCESS_KEY_ID", "test-key")
		t.Setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
		t.Setenv("AWS_SESSION_TOKEN", "")
		t.Setenv("AWS_REGION", "us-east-1")
		t.Setenv("AWS_ENDPOINT_URL_S3", endpoint)
		t.Setenv("AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", "false")
		t.Setenv("AWS_USE_FIPS_ENDPOINT", "false")
		t.Setenv("AWS_USE_DUALSTACK_ENDPOINT", "false")
		t.Setenv("AWS_CONFIG_FILE", t.TempDir()+"/missing")
		t.Setenv("AWS_SHARED_CREDENTIALS_FILE", t.TempDir()+"/missing")
	case "gs":
		t.Setenv("STORAGE_EMULATOR_HOST", endpoint)
	case "az":
		u, err := url.Parse(endpoint)
		require.NoError(t, err)
		t.Setenv("AZURE_STORAGE_ACCOUNT", "test")
		t.Setenv("AZURE_STORAGE_DOMAIN", u.Host)
		t.Setenv("AZURE_STORAGE_PROTOCOL", "http")
		t.Setenv("AZURE_STORAGE_IS_LOCAL_EMULATOR", "true")
		t.Setenv("AZURE_STORAGE_IS_CDN", "false")
		t.Setenv("AZURE_STORAGE_SAS_TOKEN", "sv=test&sig=fake")
		t.Setenv("AZURE_STORAGE_KEY", "")
		t.Setenv("AZURE_STORAGE_CONNECTION_STRING", "")
		t.Setenv("AZURE_STORAGEBLOB_CONNECTIONSTRING", "")
	}
}

type cloudWireFixture struct {
	t            *testing.T
	scheme       string
	mu           sync.Mutex
	data         []byte
	generation   int
	offsets      []int64
	listRequests int
	gzip         bool
}

func (f *cloudWireFixture) replace(data []byte) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.gzip {
		var buffer bytes.Buffer
		writer := gzip.NewWriter(&buffer)
		_, _ = writer.Write(data)
		_ = writer.Close()
		f.data = buffer.Bytes()
	} else {
		f.data = data
	}
	f.generation++
}

func (f *cloudWireFixture) serveHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	validMethod := r.Method == http.MethodGet || (f.scheme == "az" && r.Method == http.MethodHead)
	if !validMethod {
		f.t.Errorf("unexpected method: %s", r.Method)
		http.Error(w, "unexpected method", http.StatusBadRequest)
		return
	}
	switch f.scheme {
	case "s3":
		if !strings.HasPrefix(r.Header.Get("Authorization"), "AWS4-HMAC-SHA256 ") {
			f.t.Error("S3 request was not signed")
		}
		if r.URL.Query().Get("list-type") == "2" {
			f.listRequests++
			_, _ = fmt.Fprintf(
				w,
				"<ListBucketResult><Contents><Key>%s</Key></Contents></ListBucketResult>",
				wireEventKey,
			)
			return
		}
	case "az":
		if r.URL.Query().Get("sig") != "fake" {
			f.t.Error("Azure request lost its SAS token")
		}
		if r.URL.Query().Get("comp") == "list" {
			f.listRequests++
			_, _ = fmt.Fprintf(
				w,
				"<EnumerationResults><Blobs><Blob><Name>%s</Name></Blob></Blobs></EnumerationResults>",
				wireEventKey,
			)
			return
		}
	case "gs":
		if f.serveGCSMetadata(w, r) {
			return
		}
	}
	f.serveObject(w, r)
}

func (f *cloudWireFixture) serveGCSMetadata(w http.ResponseWriter, r *http.Request) bool {
	if strings.HasSuffix(r.URL.Path, "/o") {
		f.listRequests++
		_ = json.NewEncoder(w).
			Encode(map[string]any{"items": []map[string]string{{"name": wireEventKey}}})
		return true
	}
	if r.URL.Query().Get("alt") != "media" {
		attrs := map[string]string{
			"name":       wireEventKey,
			"generation": strconv.Itoa(f.generation),
			"size":       strconv.Itoa(len(f.data)),
		}
		if f.gzip {
			attrs["contentEncoding"] = "gzip"
		}
		_ = json.NewEncoder(w).Encode(attrs)
		return true
	}
	if r.URL.Query().Get("generation") != strconv.Itoa(f.generation) {
		f.t.Error("GCS reader did not open the latest generation")
	}
	w.Header().Set("X-Goog-Generation", strconv.Itoa(f.generation))
	return false
}

func (f *cloudWireFixture) serveObject(w http.ResponseWriter, r *http.Request) {
	if f.gzip {
		w.Header().Set("Content-Encoding", "gzip")
	}
	if r.Method == http.MethodHead {
		w.Header().Set("Content-Length", strconv.Itoa(len(f.data)))
		w.Header().Set("ETag", fmt.Sprintf("\"%d\"", f.generation))
		return
	}
	var offset int64
	if value := r.Header.Get("Range"); value != "" {
		if _, err := fmt.Sscanf(value, "bytes=%d-", &offset); err != nil {
			f.t.Errorf("invalid range %q: %v", value, err)
		}
	}
	f.offsets = append(f.offsets, offset)
	size := int64(len(f.data))
	if offset >= size {
		w.Header().Set("Content-Range", fmt.Sprintf("bytes */%d", size))
		w.WriteHeader(http.StatusRequestedRangeNotSatisfiable)
		return
	}
	w.Header().Set("Content-Length", strconv.FormatInt(size-offset, 10))
	if r.Header.Get("Range") != "" {
		w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", offset, size-1, size))
		w.WriteHeader(http.StatusPartialContent)
	}
	_, _ = w.Write(f.data[offset:])
}
