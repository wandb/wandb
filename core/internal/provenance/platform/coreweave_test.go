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

	"github.com/wandb/wandb/core/internal/provenance"
	"github.com/wandb/wandb/core/internal/provenance/platform"
)

func TestCoreWeaveReadsOnlyCurrentPodAndAssignedNode(t *testing.T) {
	requests := []string{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests = append(requests, r.URL.Path)
		assert.Equal(t, "Bearer scoped-token", r.Header.Get("Authorization"))
		switch r.URL.Path {
		case "/api/v1/namespaces/training/pods/current":
			_, _ = w.Write([]byte(`{"spec":{"nodeName":"private-node"}}`))
		case "/api/v1/nodes/private-node":
			_, _ = w.Write(
				[]byte(
					`{"metadata":{"labels":{"ib.coreweave.cloud/fabric":"private-fabric","ib.coreweave.cloud/leafgroup":"private-leaf","kubernetes.io/hostname":"private-node","gpu.nvidia.com/model":"H200"}}}`,
				),
			)
		default:
			t.Errorf("unexpected API request %s", r.URL.Path)
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	credentials := t.TempDir()
	require.NoError(
		t,
		os.WriteFile(filepath.Join(credentials, "token"), []byte("scoped-token"), 0o600),
	)
	redactor := provenance.NewRedactor([]byte("job-key"))
	adapter := platform.NewCoreWeave(
		platform.Config{
			SysRoot: t.TempDir(),
			Env: map[string]string{
				"K8S_POD_NAME":  "current",
				"K8S_NAMESPACE": "training",
			},
			ServiceAccountDir: credentials,
			KubernetesURL:     server.URL,
			Client:            server.Client(),
			Pseudonym:         redactor.Pseudonym,
		},
	)
	first := adapter.Collect(context.Background(), 1)
	second := adapter.Collect(context.Background(), 1)
	assert.Equal(t, first.Identity, second.Identity)
	require.Len(t, requests, 2)
	assert.Equal(t, "H200", first.Identity.AcceleratorType)
	assert.Equal(t, "missing_credentials", first.Capabilities["mission_control"].Reason)
	data, err := json.Marshal(first)
	require.NoError(t, err)
	for _, secret := range []string{"private-node", "private-fabric", "private-leaf", "scoped-token", "job-key"} {
		assert.NotContains(t, string(data), secret)
	}
	assert.NotEmpty(t, first.Topology.Levels[0].Value)
}

func TestForbiddenPodReadDoesNotListNodes(t *testing.T) {
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		http.Error(w, "private response", http.StatusForbidden)
	}))
	defer server.Close()
	credentials := t.TempDir()
	require.NoError(t, os.WriteFile(filepath.Join(credentials, "token"), []byte("token"), 0o600))
	adapter := platform.NewCoreWeave(
		platform.Config{
			SysRoot:           t.TempDir(),
			Env:               map[string]string{"K8S_POD_NAME": "pod", "K8S_NAMESPACE": "ns"},
			ServiceAccountDir: credentials,
			KubernetesURL:     server.URL,
			Client:            server.Client(),
		},
	)
	snapshot := adapter.Collect(context.Background(), 0)
	assert.Equal(t, 1, calls)
	assert.Equal(t, "permission_denied", snapshot.Capabilities["kubernetes"].Reason)
	assert.Empty(t, snapshot.Topology.Levels[0].Value)
}
