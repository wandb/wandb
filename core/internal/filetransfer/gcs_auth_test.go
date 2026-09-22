//go:build cloud_http

package filetransfer

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observabilitytest"
)

// Exercise the retained Google credential implementation, including its real
// ADC parsing, token exchange/cache and quota-project request middleware.
func TestGCSFileTransfer_ADCServiceAccount(t *testing.T) {
	var tokenCalls, objectCalls atomic.Int32
	var tokenScopes []string
	var tokenScopesMu sync.Mutex
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/token" {
			tokenCalls.Add(1)
			require.NoError(t, r.ParseForm())
			require.Equal(
				t,
				"urn:ietf:params:oauth:grant-type:jwt-bearer",
				r.Form.Get("grant_type"),
			)
			parts := strings.Split(r.Form.Get("assertion"), ".")
			require.Len(t, parts, 3)
			claimsJSON, err := base64.RawURLEncoding.DecodeString(parts[1])
			require.NoError(t, err)
			var claims struct {
				Scope string `json:"scope"`
			}
			require.NoError(t, json.Unmarshal(claimsJSON, &claims))
			tokenScopesMu.Lock()
			tokenScopes = append(tokenScopes, claims.Scope)
			tokenScopesMu.Unlock()
			w.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(
				w,
				`{"access_token":"test-access-token","token_type":"Bearer","expires_in":3600}`,
			)
			return
		}
		objectCalls.Add(1)
		require.Equal(t, "Bearer test-access-token", r.Header.Get("Authorization"))
		require.Equal(t, "test-quota-project", r.Header.Get("X-Goog-User-Project"))
		if r.URL.Query().Get("alt") == "media" {
			_, _ = io.WriteString(w, "body")
		} else {
			_, _ = io.WriteString(w, `{"generation":"1","etag":"etag","size":"4"}`)
		}
	}))
	defer server.Close()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	require.NoError(t, err)
	keyPEM := pem.EncodeToMemory(
		&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(key)},
	)
	config, err := json.Marshal(map[string]string{
		"type": "service_account", "project_id": "test-project", "private_key_id": "test-key",
		"private_key": string(keyPEM), "client_email": "test@example.iam.gserviceaccount.com",
		"token_uri": server.URL + "/token", "quota_project_id": "test-quota-project",
	})
	require.NoError(t, err)
	credentialsFile := filepath.Join(t.TempDir(), "adc.json")
	require.NoError(t, os.WriteFile(credentialsFile, config, 0o600))
	t.Setenv("GOOGLE_APPLICATION_CREDENTIALS", credentialsFile)
	t.Setenv("STORAGE_EMULATOR_HOST", "")
	t.Setenv("GOOGLE_CLOUD_UNIVERSE_DOMAIN", "googleapis.com")
	t.Setenv("GOOGLE_API_USE_CLIENT_CERTIFICATE", "false")
	t.Setenv("GOOGLE_API_USE_MTLS_ENDPOINT", "never")
	t.Setenv("GOOGLE_CLOUD_QUOTA_PROJECT", "")
	ft := NewGCSFileTransfer(nil, observabilitytest.NewTestLogger(t), NewFileTransferStats())
	ft.SetupClient()
	require.NoError(t, ft.setupErr)
	require.NotNil(t, ft.client)
	ft.endpoint = server.URL + "/storage/v1"
	for n := range 2 {
		err := ft.Download(&ReferenceArtifactDownloadTask{
			Reference: "gs://bucket/object", Digest: "etag", Size: 4,
			PathOrPrefix: filepath.Join(t.TempDir(), fmt.Sprintf("object-%d", n)),
		})
		require.NoError(t, err)
	}
	require.EqualValues(t, 1, tokenCalls.Load())
	require.EqualValues(t, 4, objectCalls.Load())
	bucket, err := newGCSReadBucket(t.Context(), "bucket", observabilitytest.NewTestLogger(t))
	require.NoError(t, err)
	bucket.(*gcsReadBucket).transfer.endpoint = server.URL + "/storage/v1"
	reader, err := bucket.NewRangeReader(t.Context(), "object", 0)
	require.NoError(t, err)
	content, err := io.ReadAll(reader)
	require.NoError(t, err)
	require.NoError(t, reader.Close())
	require.Equal(t, "body", string(content))
	require.EqualValues(t, 2, tokenCalls.Load())
	require.EqualValues(t, 6, objectCalls.Load())
	tokenScopesMu.Lock()
	defer tokenScopesMu.Unlock()
	require.Equal(t, "https://www.googleapis.com/auth/cloud-platform", tokenScopes[1])
}
