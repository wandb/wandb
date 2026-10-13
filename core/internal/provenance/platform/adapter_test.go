package platform_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/provenance/platform"
)

func TestMissingRedactionKeyOmitsSensitiveIdentity(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "Google", r.Header.Get("Metadata-Flavor"))
		switch r.URL.Path {
		case "/instance/id":
			_, _ = w.Write([]byte("instance-raw-17"))
		case "/instance/zone":
			_, _ = w.Write([]byte("projects/1/zones/us-central1-a"))
		case "/instance/machine-type":
			_, _ = w.Write([]byte("projects/1/machineTypes/a3-highgpu-8g"))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	adapter := platform.NewGCP(
		platform.Config{SysRoot: t.TempDir(), MetadataURL: server.URL, Client: server.Client()},
	)
	snapshot := adapter.Collect(context.Background(), 0)
	assert.Equal(t, "gcp", snapshot.Identity.Provider)
	assert.Empty(t, snapshot.Identity.InstanceID)
	assert.Equal(t, "us-central1-a", snapshot.Identity.Zone)
	assert.Equal(t, "partial", snapshot.Capabilities["identity_join"].Status)
	encoded, err := json.Marshal(snapshot)
	require.NoError(t, err)
	assert.NotContains(t, string(encoded), "instance-raw-17")
}

func TestIdentityJoinReportsTheEmitterKeyReason(t *testing.T) {
	for _, reason := range []string{"", "invalid_redaction_key"} {
		adapter := platform.New(platform.Config{SysRoot: t.TempDir(), KeyReason: reason})
		got := adapter.Collect(context.Background(), 0).Capabilities["identity_join"]
		want := reason
		if want == "" {
			want = "missing_redaction_key"
		}
		assert.Equal(t, platform.Capability{Status: "partial", Reason: want}, got)
	}
}

func TestProviderConflictMakesNoMetadataRequest(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "class", "dmi", "id", "sys_vendor")
	require.NoError(t, os.MkdirAll(filepath.Dir(path), 0o700))
	require.NoError(t, os.WriteFile(path, []byte("Google"), 0o600))
	adapter := platform.New(
		platform.Config{
			SysRoot: root,
			Labels:  map[string]string{"ib.coreweave.cloud/fabric": "private"},
		},
	)
	snapshot := adapter.Collect(context.Background(), 0)
	assert.Equal(t, "local", snapshot.Identity.Provider)
	assert.Equal(t, "provider_conflict", snapshot.Capabilities["provider"].Reason)
}

func TestSemanticNetworkCountersAndReset(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "class", "net", "eth0", "statistics", "tx_bytes")
	require.NoError(t, os.MkdirAll(filepath.Dir(path), 0o700))
	require.NoError(t, os.WriteFile(path, []byte("123"), 0o600))
	adapter := platform.NewLocal(platform.Config{SysRoot: root})
	first := adapter.Collect(context.Background(), 0)
	require.Len(t, first.Counters, 1)
	assert.Equal(t, "bytes", first.Counters[0].Family)
	assert.Equal(t, "bytes", first.Counters[0].Unit)
	assert.Equal(t, 123.0, *first.Counters[0].Value)
	require.NoError(t, os.WriteFile(path, []byte("12"), 0o600))
	second := adapter.Collect(context.Background(), 0)
	assert.Equal(t, "counter_reset", second.Capabilities["network"].Reason)
}

func TestProviderHintRequiresKnownValue(t *testing.T) {
	for _, hint := range []string{"coreweave", "unknown", ""} {
		adapter := platform.New(
			platform.Config{
				SysRoot: t.TempDir(),
				Env:     map[string]string{"WANDB_X_PROVENANCE_PROVIDER": hint},
			},
		)
		if hint == "coreweave" {
			assert.Equal(t, "coreweave", adapter.Name())
		} else {
			assert.Equal(t, "local", adapter.Name())
		}
	}
}
