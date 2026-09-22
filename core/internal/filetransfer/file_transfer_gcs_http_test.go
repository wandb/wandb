//go:build cloud_http

package filetransfer_test

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
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observabilitytest"
)

type gcsTestTransport struct{ target *url.URL }

func (tr gcsTestTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	clone := req.Clone(req.Context())
	clone.URL.Scheme, clone.URL.Host = tr.target.Scheme, tr.target.Host
	return http.DefaultTransport.RoundTrip(clone)
}
func newGCSTestTransfer(t *testing.T, handler http.HandlerFunc) *filetransfer.GCSFileTransfer {
	t.Helper()
	s := httptest.NewServer(handler)
	t.Cleanup(s.Close)
	u, err := url.Parse(s.URL)
	require.NoError(t, err)
	return filetransfer.NewGCSFileTransfer(
		&http.Client{Transport: gcsTestTransport{u}},
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)
}
func gcsChecksum(body []byte) string {
	var checksum [4]byte
	binary.BigEndian.PutUint32(checksum[:], crc32.Checksum(body, crc32.MakeTable(crc32.Castagnoli)))
	return base64.StdEncoding.EncodeToString(checksum[:])
}
func gcsMetadata(w http.ResponseWriter, body []byte, generation, etag string) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).
		Encode(map[string]any{"generation": generation, "etag": etag, "size": fmt.Sprint(len(body)), "crc32c": gcsChecksum(body)})
}
func gcsSingleTask(t *testing.T, name string) *filetransfer.ReferenceArtifactDownloadTask {
	t.Helper()
	return &filetransfer.ReferenceArtifactDownloadTask{
		Reference:    "gs://bucket/" + url.PathEscape(name),
		Digest:       "etag",
		Size:         1,
		PathOrPrefix: filepath.Join(t.TempDir(), "out"),
	}
}
func TestGCSFileTransfer_Download(t *testing.T) {
	for _, ref := range []string{"", "s3://bucket/key", "gs:///key"} {
		t.Run(ref, func(t *testing.T) {
			ft := newGCSTestTransfer(
				t,
				func(w http.ResponseWriter, r *http.Request) { t.Error("unexpected request") },
			)
			require.Error(
				t,
				ft.Download(&filetransfer.ReferenceArtifactDownloadTask{Reference: ref}),
			)
		})
	}
}
func TestGCSFileTransfer_EncodedObjectAndGeneration(t *testing.T) {
	name := "dir/a b%?#雪.txt"
	body := []byte("downloaded data")
	var calls atomic.Int32
	ft := newGCSTestTransfer(t, func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		require.Equal(t, "/storage/v1/b/bucket/o/"+url.PathEscape(name), r.URL.EscapedPath())
		require.Equal(t, "17", r.URL.Query().Get("generation"))
		if r.URL.Query().Get("alt") == "media" {
			w.Header().Set("X-Goog-Generation", "17")
			_, _ = w.Write(body)
		} else {
			gcsMetadata(w, body, "17", "etag")
		}
	})
	task := gcsSingleTask(t, name)
	task.VersionId = float64(17)
	require.NoError(t, ft.Download(task))
	got, err := os.ReadFile(task.PathOrPrefix)
	require.NoError(t, err)
	require.Equal(t, body, got)
	require.EqualValues(t, 2, calls.Load())
}
func TestGCSFileTransfer_Pagination(t *testing.T) {
	var pages atomic.Int32
	ft := newGCSTestTransfer(t, func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/o") {
			pages.Add(1)
			require.Equal(t, "prefix/", r.URL.Query().Get("prefix"))
			if r.URL.Query().Get("pageToken") == "" {
				_, _ = io.WriteString(
					w,
					`{"items":[{"name":"prefix/a"},{"name":"prefix/folder/"}],"nextPageToken":"token /+=?"}`,
				)
			} else {
				require.Equal(t, "token /+=?", r.URL.Query().Get("pageToken"))
				_, _ = io.WriteString(w, `{"items":[{"name":"prefix/nested/b"}]}`)
			}
			return
		}
		body := []byte(r.URL.Path[strings.LastIndex(r.URL.Path, "/")+1:])
		if r.URL.Query().Get("alt") == "media" {
			require.Equal(t, "123", r.URL.Query().Get("generation"))
			_, _ = w.Write(body)
		} else {
			gcsMetadata(w, body, "123", "ignored-for-prefix")
		}
	})
	task := &filetransfer.ReferenceArtifactDownloadTask{
		Reference:    "gs://bucket/prefix/",
		Digest:       "gs://bucket/prefix/",
		PathOrPrefix: t.TempDir(),
	}
	require.NoError(t, ft.Download(task))
	for _, name := range []string{"a", "nested/b"} {
		got, err := os.ReadFile(filepath.Join(task.PathOrPrefix, name))
		require.NoError(t, err)
		require.Equal(t, filepath.Base(name), string(got))
	}
	require.EqualValues(t, 2, pages.Load())
}
func TestGCSFileTransfer_DigestMismatch(t *testing.T) {
	ft := newGCSTestTransfer(t, func(w http.ResponseWriter, r *http.Request) {
		require.Empty(t, r.URL.Query().Get("alt"))
		gcsMetadata(w, []byte("body"), "1", "different")
	})
	task := gcsSingleTask(t, "object")
	require.ErrorContains(t, ft.Download(task), "digest/etag mismatch")
	_, err := os.Stat(task.PathOrPrefix)
	require.True(t, os.IsNotExist(err))
}
func TestGCSFileTransfer_DirectorySentinels(t *testing.T) {
	for _, name := range []string{"folder", "folder/"} {
		t.Run(name, func(t *testing.T) {
			var calls atomic.Int32
			ft := newGCSTestTransfer(t, func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				if strings.HasSuffix(r.URL.Path, "/folder/") {
					gcsMetadata(w, nil, "1", "etag")
				} else {
					http.NotFound(w, r)
				}
			})
			task := gcsSingleTask(t, name)
			task.Size = 0
			require.NoError(t, ft.Download(task))
			if strings.HasSuffix(name, "/") {
				require.Zero(t, calls.Load())
			} else {
				require.EqualValues(t, 2, calls.Load())
			}
			_, err := os.Stat(task.PathOrPrefix)
			require.True(t, os.IsNotExist(err))
		})
	}
}
func TestGCSFileTransfer_ErrorsPreserveDestination(t *testing.T) {
	for _, failure := range []string{"checksum", "generation", "precondition", "missing", "malformed-metadata", "invalid-checksum"} {
		t.Run(failure, func(t *testing.T) {
			ft := newGCSTestTransfer(t, func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Query().Get("alt") == "" {
					switch failure {
					case "missing":
						http.NotFound(w, r)
					case "malformed-metadata":
						_, _ = io.WriteString(w, `{"size":"1"}`)
					case "invalid-checksum":
						_, _ = io.WriteString(
							w,
							`{"generation":"1","etag":"etag","size":"4","crc32c":"bad"}`,
						)
					default:
						gcsMetadata(w, []byte("body"), "1", "etag")
					}
					return
				}
				switch failure {
				case "checksum":
					_, _ = io.WriteString(w, "oops")
				case "generation":
					w.Header().Set("X-Goog-Generation", "2")
					_, _ = io.WriteString(w, "body")
				case "precondition":
					http.Error(w, "precondition failed", http.StatusPreconditionFailed)
				}
			})
			task := gcsSingleTask(t, "object.txt")
			require.NoError(t, os.WriteFile(task.PathOrPrefix, []byte("old"), 0o600))
			require.Error(t, ft.Download(task))
			got, err := os.ReadFile(task.PathOrPrefix)
			require.NoError(t, err)
			require.Equal(t, "old", string(got))
			files, err := filepath.Glob(
				filepath.Join(filepath.Dir(task.PathOrPrefix), ".wandb-gcs-*"),
			)
			require.NoError(t, err)
			require.Empty(t, files)
		})
	}
}
func TestGCSFileTransfer_ResumesInterruptedBody(t *testing.T) {
	for _, response := range []string{"valid", "ignores-range", "wrong-offset"} {
		t.Run(response, func(t *testing.T) {
			body := []byte("0123456789")
			var reads atomic.Int32
			ft := newGCSTestTransfer(t, func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Query().Get("alt") == "" {
					gcsMetadata(w, body, "9", "etag")
					return
				}
				require.Equal(t, "9", r.URL.Query().Get("generation"))
				if reads.Add(1) == 1 {
					w.Header().Set("Content-Length", "10")
					_, _ = w.Write(body[:4])
					return
				}
				require.Equal(t, "bytes=4-", r.Header.Get("Range"))
				switch response {
				case "ignores-range":
					_, _ = w.Write(body)
				case "wrong-offset":
					w.Header().Set("Content-Range", "bytes 3-9/10")
					w.WriteHeader(http.StatusPartialContent)
					_, _ = w.Write(body[3:])
				default:
					w.Header().Set("Content-Range", "bytes 4-9/10")
					w.WriteHeader(http.StatusPartialContent)
					_, _ = w.Write(body[4:])
				}
			})
			task := gcsSingleTask(t, "object")
			err := ft.Download(task)
			if response == "valid" {
				require.NoError(t, err)
				got, err := os.ReadFile(task.PathOrPrefix)
				require.NoError(t, err)
				require.Equal(t, body, got)
			} else {
				require.Error(t, err)
			}
			require.EqualValues(t, 2, reads.Load())
		})
	}
}
func TestGCSFileTransfer_Gzip(t *testing.T) {
	body := []byte(strings.Repeat("compressible content", 10))
	var compressed bytes.Buffer
	zw := gzip.NewWriter(&compressed)
	_, err := zw.Write(body)
	require.NoError(t, err)
	require.NoError(t, zw.Close())
	for _, transcode := range []bool{false, true} {
		t.Run(fmt.Sprint(transcode), func(t *testing.T) {
			ft := newGCSTestTransfer(t, func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Query().Get("alt") == "" {
					gcsMetadata(w, compressed.Bytes(), "1", "etag")
					return
				}
				require.Equal(t, "gzip", r.Header.Get("Accept-Encoding"))
				w.Header().Set("X-Goog-Stored-Content-Encoding", "gzip")
				if transcode {
					_, _ = w.Write(body)
				} else {
					w.Header().Set("Content-Encoding", "gzip")
					_, _ = w.Write(compressed.Bytes())
				}
			})
			task := gcsSingleTask(t, "object")
			require.NoError(t, ft.Download(task))
			got, err := os.ReadFile(task.PathOrPrefix)
			require.NoError(t, err)
			require.Equal(t, body, got)
		})
	}
}
func TestGCSFileTransfer_EmulatorWithoutCredentials(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		require.Empty(t, r.Header.Get("Authorization"))
		if r.URL.Query().Get("alt") == "" {
			gcsMetadata(w, []byte("body"), "1", "etag")
		} else {
			_, _ = io.WriteString(w, "body")
		}
	}))
	defer s.Close()
	t.Setenv("STORAGE_EMULATOR_HOST", strings.TrimPrefix(s.URL, "http://"))
	t.Setenv("GOOGLE_APPLICATION_CREDENTIALS", "/nonexistent/credentials.json")
	ft := filetransfer.NewGCSFileTransfer(
		nil,
		observabilitytest.NewTestLogger(t),
		filetransfer.NewFileTransferStats(),
	)
	require.NoError(t, ft.Download(gcsSingleTask(t, "object")))
}

func TestGCSFileTransfer_RetriesTransientResponse(t *testing.T) {
	var attempts atomic.Int32
	ft := newGCSTestTransfer(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("alt") == "" {
			if attempts.Add(1) == 1 {
				http.Error(w, "retry", http.StatusServiceUnavailable)
				return
			}
			gcsMetadata(w, []byte("body"), "1", "etag")
		} else {
			_, _ = io.WriteString(w, "body")
		}
	})
	require.NoError(t, ft.Download(gcsSingleTask(t, "object")))
	require.EqualValues(t, 2, attempts.Load())
}

func TestGCSFileTransfer_BoundedStreamRetries(t *testing.T) {
	var reads atomic.Int32
	ft := newGCSTestTransfer(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("alt") == "" {
			gcsMetadata(w, []byte("0123456789"), "1", "etag")
			return
		}
		offset := int(reads.Add(1) - 1)
		w.Header().Set("Content-Length", fmt.Sprint(10-offset))
		if offset > 0 {
			require.Equal(t, fmt.Sprintf("bytes=%d-", offset), r.Header.Get("Range"))
			w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-9/10", offset))
			w.WriteHeader(http.StatusPartialContent)
		}
		_, _ = fmt.Fprint(w, offset)
	})
	task := gcsSingleTask(t, "object")
	require.ErrorContains(t, ft.Download(task), "after 5 stream attempts")
	require.EqualValues(t, 5, reads.Load())
	_, err := os.Stat(task.PathOrPrefix)
	require.True(t, os.IsNotExist(err))
}

func TestGCSFileTransfer_RejectsUnsafeObjectPath(t *testing.T) {
	ft := newGCSTestTransfer(t, func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/o") {
			_, _ = io.WriteString(w, `{"items":[{"name":"prefix/../../escape"}]}`)
		} else {
			require.Empty(t, r.URL.Query().Get("alt"))
			gcsMetadata(w, nil, "1", "etag")
		}
	})
	task := &filetransfer.ReferenceArtifactDownloadTask{
		Reference:    "gs://bucket/prefix/",
		Digest:       "gs://bucket/prefix/",
		PathOrPrefix: t.TempDir(),
	}
	require.ErrorContains(t, ft.Download(task), "invalid GCS relative object path")
}

func TestGCSFileTransfer_UnsupportedEndpointConfiguration(t *testing.T) {
	for _, config := range []struct{ key, value, want string }{
		{"GOOGLE_CLOUD_UNIVERSE_DOMAIN", "example.com", "does not support universe domain"},
		{"GOOGLE_API_USE_MTLS_ENDPOINT", "always", "does not support mandatory mTLS"},
	} {
		t.Run(config.key, func(t *testing.T) {
			t.Setenv("STORAGE_EMULATOR_HOST", "")
			t.Setenv("GOOGLE_APPLICATION_CREDENTIALS", "/nonexistent/credentials.json")
			t.Setenv(config.key, config.value)
			ft := filetransfer.NewGCSFileTransfer(
				nil,
				observabilitytest.NewTestLogger(t),
				filetransfer.NewFileTransferStats(),
			)
			require.ErrorContains(t, ft.Download(gcsSingleTask(t, "object")), config.want)
		})
	}
}

func TestGCSFileTransfer_PreservesDownloadPermissions(t *testing.T) {
	for _, existingMode := range []os.FileMode{0, 0o640, 0o750} {
		t.Run(fmt.Sprintf("%04o", existingMode), func(t *testing.T) {
			ft := newGCSTestTransfer(t, func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Query().Get("alt") == "media" {
					_, _ = io.WriteString(w, "body")
				} else {
					gcsMetadata(w, []byte("body"), "1", "etag")
				}
			})
			task := gcsSingleTask(t, "object")
			// Derive the effective creation mode without reading or changing the global umask.
			reference := filepath.Join(filepath.Dir(task.PathOrPrefix), "mode-reference")
			require.NoError(t, os.WriteFile(reference, nil, 0o666))
			referenceInfo, err := os.Stat(reference)
			require.NoError(t, err)
			expectedMode := referenceInfo.Mode().Perm()
			if existingMode != 0 {
				require.NoError(t, os.WriteFile(task.PathOrPrefix, []byte("previous"), 0o600))
				require.NoError(t, os.Chmod(task.PathOrPrefix, existingMode))
				info, err := os.Stat(task.PathOrPrefix)
				require.NoError(t, err)
				expectedMode = info.Mode().Perm()
			}
			require.NoError(t, ft.Download(task))
			info, err := os.Stat(task.PathOrPrefix)
			require.NoError(t, err)
			require.Equal(t, expectedMode, info.Mode().Perm())
			body, err := os.ReadFile(task.PathOrPrefix)
			require.NoError(t, err)
			require.Equal(t, "body", string(body))
			leftovers, err := filepath.Glob(
				filepath.Join(filepath.Dir(task.PathOrPrefix), ".wandb-gcs-*"),
			)
			require.NoError(t, err)
			require.Empty(t, leftovers)
		})
	}
}

func TestGCSFileTransfer_ExactPrefixObject(t *testing.T) {
	ft := newGCSTestTransfer(t, func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/o"):
			require.Equal(t, "object", r.URL.Query().Get("prefix"))
			_, _ = io.WriteString(w, `{"items":[{"name":"object"}]}`)
		case r.URL.Query().Get("alt") == "media":
			_, _ = io.WriteString(w, "body")
		default:
			gcsMetadata(w, []byte("body"), "1", "etag")
		}
	})
	task := gcsSingleTask(t, "object")
	task.Digest = task.Reference // checksum=False: enumerate names with this prefix.
	require.NoError(t, ft.Download(task))
	body, err := os.ReadFile(task.PathOrPrefix)
	require.NoError(t, err)
	require.Equal(t, "body", string(body))
}
