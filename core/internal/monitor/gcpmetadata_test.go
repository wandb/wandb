package monitor

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestProbeGoogleCloud(t *testing.T) {
	values := map[string]string{
		"/computeMetadata/v1/project/project-id":               "wandb-test",
		"/computeMetadata/v1/instance/zone":                    "projects/123/zones/us-central1-b",
		"/computeMetadata/v1/instance/id":                      "987654321",
		"/computeMetadata/v1/instance/attributes/cluster-name": "train-cluster",
	}
	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			value, ok := values[r.URL.Path]
			if !ok || r.Header.Get("Metadata-Flavor") != "Google" {
				http.NotFound(w, r)
				return
			}
			_, _ = w.Write([]byte(value))
		},
	))
	defer server.Close()
	// Points the metadata client at the server instead of 169.254.169.254.
	t.Setenv("GCE_METADATA_HOST", strings.TrimPrefix(server.URL, "http://"))

	e := probeGoogleCloud(context.Background())

	require.NotNil(t, e)
	assert.Equal(t, "wandb-test", e.GoogleCloud.ProjectId)
	assert.Equal(t, "us-central1-b", e.GoogleCloud.Zone)
	assert.Equal(t, "987654321", e.GoogleCloud.InstanceId)
	assert.Equal(t, "train-cluster", e.GoogleCloud.ClusterName)
}
