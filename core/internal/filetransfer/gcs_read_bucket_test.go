//go:build cloud_http

package filetransfer

import (
	"bytes"
	"compress/gzip"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"hash/crc32"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observabilitytest"
)

func newGCSBucketTest(t *testing.T, handler http.HandlerFunc) *gcsReadBucket {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	ft := NewGCSFileTransfer(server.Client(), observabilitytest.NewTestLogger(t), nil)
	ft.endpoint = server.URL + "/storage/v1"
	return &gcsReadBucket{transfer: ft, bucket: "bucket"}
}

func writeGCSBucketMetadata(w http.ResponseWriter, body []byte, generation, encoding string) {
	var checksum [4]byte
	binary.BigEndian.PutUint32(checksum[:], crc32.Checksum(body, crc32.MakeTable(crc32.Castagnoli)))
	_ = json.NewEncoder(w).Encode(gcsObjectAttrs{
		Size: int64(len(body)), Generation: generation, ContentEncoding: encoding,
		CRC32C: base64.StdEncoding.EncodeToString(checksum[:]),
	})
}

func TestGCSReadBucket_GrowingObjectRanges(t *testing.T) {
	contents := map[string][]byte{"1": []byte("hello"), "2": []byte("hello world")}
	var current atomic.Int32
	current.Store(1)
	var mu sync.Mutex
	var generations []string
	bucket := newGCSBucketTest(t, func(w http.ResponseWriter, r *http.Request) {
		require.Equal(
			t,
			"/storage/v1/b/bucket/o/"+url.PathEscape("events/a +%?雪"),
			r.URL.EscapedPath(),
		)
		if r.URL.Query().Get("alt") != "media" {
			generation := fmt.Sprint(current.Load())
			writeGCSBucketMetadata(w, contents[generation], generation, "")
			return
		}
		generation := r.URL.Query().Get("generation")
		mu.Lock()
		generations = append(generations, generation)
		mu.Unlock()
		data := contents[generation]
		w.Header().Set("X-Goog-Generation", generation)
		var offset int
		if header := r.Header.Get("Range"); header != "" {
			_, err := fmt.Sscanf(header, "bytes=%d-", &offset)
			require.NoError(t, err)
			w.Header().
				Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", offset, len(data)-1, len(data)))
			w.WriteHeader(http.StatusPartialContent)
		}
		_, _ = w.Write(data[offset:])
	})
	key := "events/a +%?雪"
	first, err := bucket.NewRangeReader(t.Context(), key, 0)
	require.NoError(t, err)
	current.Store(2)
	got, err := io.ReadAll(first)
	require.NoError(t, err)
	require.NoError(t, first.Close())
	require.Equal(t, "hello", string(got))
	reader, err := bucket.NewRangeReader(t.Context(), key, 5)
	require.NoError(t, err)
	got, err = io.ReadAll(reader)
	require.NoError(t, err)
	require.NoError(t, reader.Close())
	require.Equal(t, " world", string(got))
	for _, offset := range []int64{11, 12} {
		reader, err = bucket.NewRangeReader(t.Context(), key, offset)
		require.NoError(t, err)
		got, err = io.ReadAll(reader)
		require.NoError(t, err)
		require.Empty(t, got)
		require.NoError(t, reader.Close())
	}
	mu.Lock()
	defer mu.Unlock()
	require.Equal(t, []string{"1", "2"}, generations)
}

func TestGCSReadBucket_GzipDecodedOffsets(t *testing.T) {
	data := []byte(strings.Repeat("decoded event bytes ", 100))
	var encoded bytes.Buffer
	gz := gzip.NewWriter(&encoded)
	_, err := gz.Write(data)
	require.NoError(t, err)
	require.NoError(t, gz.Close())
	for _, transcode := range []bool{false, true} {
		t.Run(strconv.FormatBool(transcode), func(t *testing.T) {
			bucket := newGCSBucketTest(t, func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Query().Get("alt") != "media" {
					writeGCSBucketMetadata(w, encoded.Bytes(), "7", "gzip")
					return
				}
				require.Equal(t, "7", r.URL.Query().Get("generation"))
				require.Empty(t, r.Header.Get("Range"))
				require.Equal(t, "gzip", r.Header.Get("Accept-Encoding"))
				w.Header().Set("X-Goog-Stored-Content-Encoding", "gzip")
				if transcode {
					_, _ = w.Write(data)
				} else {
					w.Header().Set("Content-Encoding", "gzip")
					_, _ = w.Write(encoded.Bytes())
				}
			})
			for _, offset := range []int64{5, int64(len(data)), int64(len(data) + 1)} {
				reader, err := bucket.NewRangeReader(t.Context(), "events", offset)
				require.NoError(t, err)
				got, err := io.ReadAll(reader)
				require.NoError(t, err)
				require.NoError(t, reader.Close())
				require.Equal(t, data[min(offset, int64(len(data))):], got)
			}
		})
	}
}

func TestGCSReadBucket_ListPagesAndGoCDKEncoding(t *testing.T) {
	prefix := "events/../a\n"
	var calls atomic.Int32
	bucket := newGCSBucketTest(t, func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		require.Equal(t, "events/..__0x2f__a__0xa__", r.URL.Query().Get("prefix"))
		require.Equal(t, "1000", r.URL.Query().Get("maxResults"))
		switch r.URL.Query().Get("pageToken") {
		case "":
			_ = json.NewEncoder(w).Encode(map[string]any{"items": []map[string]string{
				{"name": "events/..__0x2f__a__0xa__z"}, {"name": "events/..__0x2f__a__0xa__b"},
			}, "nextPageToken": "next +/?"})
		case "next +/?":
			_ = json.NewEncoder(w).
				Encode(map[string]any{"items": []map[string]string{{"name": "events/..__0x2f__a__0xa__雪"}}})
		default:
			t.Error("unexpected token")
		}
	})
	page, err := bucket.ListPage(t.Context(), prefix, "")
	require.NoError(t, err)
	require.Equal(t, []string{prefix + "b", prefix + "z"}, page.Keys)
	require.Equal(t, "next +/?", page.NextToken)
	page, err = bucket.ListPage(t.Context(), prefix, page.NextToken)
	require.NoError(t, err)
	require.Equal(t, []string{prefix + "雪"}, page.Keys)
	require.Empty(t, page.NextToken)
	require.EqualValues(t, 2, calls.Load())
}

func TestGCSReadBucket_UsesGoCDKKeyEncoding(t *testing.T) {
	key := "events/../a\r\n雪"
	bucket := newGCSBucketTest(t, func(w http.ResponseWriter, r *http.Request) {
		require.Equal(t, "/storage/v1/b/bucket/o/events/..__0x2f__a__0xd____0xa__雪", r.URL.Path)
		if r.URL.Query().Get("alt") == "media" {
			_, _ = io.WriteString(w, "data")
		} else {
			writeGCSBucketMetadata(w, []byte("data"), "1", "")
		}
	})
	reader, err := bucket.NewRangeReader(t.Context(), key, 0)
	require.NoError(t, err)
	got, err := io.ReadAll(reader)
	require.NoError(t, err)
	require.NoError(t, reader.Close())
	require.Equal(t, "data", string(got))
}

func TestGCSReadBucket_EmulatorAndValidation(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		require.Empty(t, r.Header.Get("Authorization"))
		if r.URL.Query().Get("alt") == "media" {
			_, _ = io.WriteString(w, "data")
		} else {
			writeGCSBucketMetadata(w, []byte("data"), "1", "")
		}
	}))
	defer server.Close()
	t.Setenv("STORAGE_EMULATOR_HOST", strings.TrimPrefix(server.URL, "http://"))
	t.Setenv("GOOGLE_APPLICATION_CREDENTIALS", "/nonexistent/credentials.json")
	bucket, err := newGCSReadBucket(t.Context(), "bucket", observabilitytest.NewTestLogger(t))
	require.NoError(t, err)
	reader, err := bucket.NewRangeReader(t.Context(), "events", 0)
	require.NoError(t, err)
	got, err := io.ReadAll(reader)
	require.NoError(t, err)
	require.NoError(t, reader.Close())
	require.Equal(t, "data", string(got))
	_, err = bucket.NewRangeReader(t.Context(), "events", -1)
	require.Error(t, err)
	_, err = bucket.NewRangeReader(t.Context(), "", 0)
	require.Error(t, err)
	_, err = newGCSReadBucket(t.Context(), "", nil)
	require.Error(t, err)
	t.Setenv("STORAGE_EMULATOR_HOST", "")
	_, err = newGCSReadBucket(t.Context(), "bucket", nil)
	require.Error(t, err)
	require.Contains(t, err.Error(), os.Getenv("GOOGLE_APPLICATION_CREDENTIALS"))
}
