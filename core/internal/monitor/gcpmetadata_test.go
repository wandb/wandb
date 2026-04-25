package monitor_test

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observabilitytest"
)

func TestGoogleCloudMetadataProbeNotGCP(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("123456789"))
	}))
	defer server.Close()

	gcm := newTestGoogleCloudMetadata(t, server)

	assert.Nil(t, gcm.Probe(context.Background()))
}

func TestGoogleCloudMetadataProbeGCE(t *testing.T) {
	t.Setenv("KUBERNETES_SERVICE_HOST", "")
	server := newGoogleCloudMetadataServer(t, map[string]string{
		"/instance/id":        "123456789",
		"/project/project-id": "wandb-test",
		"/instance/zone":      "projects/123/zones/us-central1-b",
	})
	defer server.Close()

	gcm := newTestGoogleCloudMetadata(t, server)

	env := gcm.Probe(context.Background())
	require.NotNil(t, env)
	require.NotNil(t, env.GoogleCloud)
	assert.Equal(t, "wandb-test", env.GoogleCloud.ProjectId)
	assert.Equal(t, "123456789", env.GoogleCloud.InstanceId)
	assert.Equal(t, "us-central1-b", env.GoogleCloud.Zone)
	assert.Equal(t, "us-central1", env.GoogleCloud.Region)
	assert.Equal(t, "GCE", env.GoogleCloud.Orchestrator)
	assert.Nil(t, env.GoogleCloud.Gke)
}

func TestGoogleCloudMetadataProbeGKEWithDiagonEnv(t *testing.T) {
	t.Setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
	t.Setenv(
		"GKE_DIAGON_IDENTIFIER",
		`{"metadata.name":"trainer","metadata.kind":"JobSet","clustername":"projects/p/locations/us-central1/clusters/train-cluster","namespace":"ml"}`,
	)
	t.Setenv(
		"GKE_DIAGON_METADATA",
		`{"parent-workload":"parent-jobset","creation-timestamp":"2026-04-24T03:04:05Z","associated-labels":"app=trainer,team=infra"}`,
	)
	server := newGoogleCloudMetadataServer(t, map[string]string{
		"/instance/id":        "987654321",
		"/project/project-id": "wandb-prod",
		"/instance/zone":      "projects/123/zones/europe-west4-a",
	})
	defer server.Close()

	gcm := newTestGoogleCloudMetadata(t, server)

	env := gcm.Probe(context.Background())
	require.NotNil(t, env)
	require.NotNil(t, env.GoogleCloud)
	require.NotNil(t, env.GoogleCloud.Gke)

	assert.Equal(t, "GKE", env.GoogleCloud.Orchestrator)
	assert.Equal(t, "europe-west4", env.GoogleCloud.Region)
	assert.Equal(t, "train-cluster", env.GoogleCloud.Gke.ClusterName)
	assert.Equal(t, "ml", env.GoogleCloud.Gke.Namespace)
	assert.Equal(t, "JobSet", env.GoogleCloud.Gke.WorkloadKind)
	assert.Equal(t, "trainer", env.GoogleCloud.Gke.WorkloadName)
	assert.Equal(t, "parent-jobset", env.GoogleCloud.Gke.ParentWorkload)
	assert.Equal(t, "2026-04-24T03:04:05Z", env.GoogleCloud.Gke.CreationTimestamp)
	assert.Equal(
		t,
		sha256Hex("train-cluster_ml_JobSet_trainer_20260424-030405"),
		env.GoogleCloud.Gke.WorkloadId,
	)
	assert.Equal(
		t,
		map[string]string{"app": "trainer", "team": "infra"},
		env.GoogleCloud.Gke.Labels,
	)
}

func newGoogleCloudMetadataServer(t *testing.T, responses map[string]string) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "Google", r.Header.Get("Metadata-Flavor"))
		value, ok := responses[r.URL.Path]
		if !ok {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Metadata-Flavor", "Google")
		_, _ = w.Write([]byte(value))
	}))
}

func newTestGoogleCloudMetadata(
	t *testing.T, server *httptest.Server) *monitor.GoogleCloudMetadata {
	t.Helper()
	logger := observabilitytest.NewTestLogger(t)
	gcm, err := monitor.NewGoogleCloudMetadata(monitor.GoogleCloudMetadataParams{
		Client:                  server.Client(),
		BaseURL:                 server.URL,
		KubernetesSATokenPath:   filepath.Join(t.TempDir(), "missing-token"),
		KubernetesNamespacePath: filepath.Join(t.TempDir(), "namespace"),
		Logger:                  logger,
	})
	require.NoError(t, err)
	return gcm
}

func sha256Hex(value string) string {
	hash := sha256.Sum256([]byte(value))
	return hex.EncodeToString(hash[:])
}
