package provenance_test

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/provenance"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type catalogManifest struct {
	PeakFLOPs    *provenance.PeakFLOPs            `json:"peak_flops"`
	Build        *provenance.Build                `json:"build"`
	Capabilities map[string]provenance.Capability `json:"capabilities"`
}

func boundManifest(t *testing.T, deviceName string) catalogManifest {
	t.Helper()
	dir := t.TempDir()
	emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir})
	emitter.SetEnvironment(
		&spb.EnvironmentRecord{
			GpuNvidia: []*spb.GpuNvidiaInfo{{Uuid: "GPU-private", Name: deviceName}},
		},
	)
	t.Setenv("WANDB_X_PROVENANCE_REDACTION_KEY", strings.Repeat("ab", 32))
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
	emitter.AddRecord(
		provenance.Record{
			Kind: "binding",
			PayloadJSON: []byte(
				`{"gpu_uuid_hmac":"gpu_uuid_b9ace856f2313cfd555be18d","status":"available"}`,
			),
			MonotonicNS: 1,
		},
	)
	emitter.OnSample(nil, nil)
	emitter.Drain()
	data, err := os.ReadFile(filepath.Join(dir, "wandb-telemetry", "v2", "manifest", "writer.json"))
	require.NoError(t, err)
	var manifest catalogManifest
	require.NoError(t, json.Unmarshal(data, &manifest))
	return manifest
}

func TestV2ManifestCarriesPeakFLOPsForCatalogDevice(t *testing.T) {
	manifest := boundManifest(t, "NVIDIA H100 80GB HBM3")
	require.NotNil(t, manifest.PeakFLOPs)
	assert.Equal(t, provenance.PeakFLOPsCatalogVersion, manifest.PeakFLOPs.CatalogVersion)
	assert.Equal(t, "H100 SXM", manifest.PeakFLOPs.Device)
	assert.Equal(t, "bf16", manifest.PeakFLOPs.DType)
	assert.InDelta(t, 989.4e12, manifest.PeakFLOPs.PerGPU, 1)
	assert.InDelta(t, 1978.9e12, manifest.PeakFLOPs.PerGPUByDType["fp8"], 1)
	assert.Equal(t, "available", manifest.Capabilities["peak_flops"].Status)
	assert.Equal(
		t,
		provenance.Capability{Status: "unavailable", Reason: "not_provided"},
		manifest.Capabilities["pricing"],
	)
}

func TestV2ManifestOmitsPeakFLOPsForUnknownDevice(t *testing.T) {
	manifest := boundManifest(t, "Example GPU")
	assert.Nil(t, manifest.PeakFLOPs)
	assert.Equal(
		t,
		provenance.Capability{Status: "unavailable", Reason: "device_not_in_catalog"},
		manifest.Capabilities["peak_flops"],
	)
}

func TestV2ManifestCarriesLauncherBuildIdentity(t *testing.T) {
	commit := strings.Repeat("a", 40)
	digest := strings.Repeat("b", 64)
	cases := []struct {
		name  string
		env   map[string]string
		build *provenance.Build
		want  provenance.Capability
	}{
		{
			"absent",
			map[string]string{},
			nil,
			provenance.Capability{Status: "unavailable", Reason: "not_provided"},
		},
		{
			"complete",
			map[string]string{
				"WANDB_X_PROVENANCE_BUILD_BASE_COMMIT":        commit,
				"WANDB_X_PROVENANCE_BUILD_SOURCE_DIFF_SHA256": digest,
				"WANDB_X_PROVENANCE_BUILD_WHEEL_SHA256":       digest,
				"WANDB_X_PROVENANCE_BUILD_IMAGE_DIGEST":       "sha256:" + digest,
			},
			&provenance.Build{
				BaseCommit:       commit,
				SourceDiffSHA256: digest,
				WheelSHA256:      digest,
				ImageDigest:      "sha256:" + digest,
			},
			provenance.Capability{Status: "available"},
		},
		{
			"invalid image digest",
			map[string]string{
				"WANDB_X_PROVENANCE_BUILD_BASE_COMMIT":  commit,
				"WANDB_X_PROVENANCE_BUILD_IMAGE_DIGEST": "latest",
			},
			&provenance.Build{BaseCommit: commit},
			provenance.Capability{Status: "partial", Reason: "invalid_build_identity"},
		},
		{
			"commit only",
			map[string]string{"WANDB_X_PROVENANCE_BUILD_BASE_COMMIT": commit},
			&provenance.Build{BaseCommit: commit},
			provenance.Capability{Status: "partial", Reason: "incomplete_build_identity"},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			for key, value := range tc.env {
				t.Setenv(key, value)
			}
			manifest := boundManifest(t, "NVIDIA H100 80GB HBM3")
			assert.Equal(t, tc.build, manifest.Build)
			assert.Equal(t, tc.want, manifest.Capabilities["build_identity"])
		})
	}
}
