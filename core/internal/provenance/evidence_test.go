package provenance_test

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/provenance"
	"github.com/wandb/wandb/core/internal/provenance/platform"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type evidenceManifest struct {
	Capabilities map[string]provenance.Capability `json:"capabilities"`
	Exit         *provenance.Exit                 `json:"exit"`
	Platform     *platform.Snapshot               `json:"platform"`
}

func readManifest(t *testing.T, dir string) evidenceManifest {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(dir, "wandb-telemetry", "v2", "manifest", "writer.json"))
	require.NoError(t, err)
	var manifest evidenceManifest
	require.NoError(t, json.Unmarshal(data, &manifest))
	return manifest
}

func TestTerminateRecordsTheSignalExitInTheFinalManifest(t *testing.T) {
	dir := t.TempDir()
	work := &exitWork{}
	emitter := provenance.NewEmitter(
		&provenance.EmitterParams{FilesDir: dir, WriterID: "writer", Work: work},
	)
	require.True(t, emitter.Handshake(&spb.ProvenanceStartRequest{ProtocolVersion: 2}).Accepted)
	provenance.Terminate(time.Second, 143)
	emitter.SetExit(143, "finish")
	emitter.Drain()
	assert.Equal(t, &provenance.Exit{Code: 143, Reason: "terminated"}, readManifest(t, dir).Exit)
}

func TestGPUMetricsCapabilityExplainsAMissingJoin(t *testing.T) {
	bound := `{"gpu_uuid_hmac":"gpu_uuid_3eb65075498508521b048895","status":"available"}`
	other := `{"gpu_uuid_hmac":"gpu_uuid_aaaaaaaaaaaaaaaaaaaaaaaa","status":"available"}`
	for _, tc := range []struct {
		name        string
		environment bool
		key         string
		binding     string
		want        provenance.Capability
		gaps        int64
	}{
		{"not probed", false, strings.Repeat("ab", 32), bound, provenance.Capability{Status: "unavailable", Reason: "environment_not_probed"}, 0},
		{"no key", true, "", "", provenance.Capability{Status: "unavailable", Reason: "missing_redaction_key"}, 1},
		{"no binding", true, strings.Repeat("ab", 32), "", provenance.Capability{Status: "unavailable", Reason: "binding_not_proven"}, 1},
		{"other gpu", true, strings.Repeat("ab", 32), other, provenance.Capability{Status: "unavailable", Reason: "binding_not_joined"}, 1},
		{"joined", true, strings.Repeat("ab", 32), bound, provenance.Capability{Status: "available"}, 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir})
			if tc.environment {
				emitter.SetEnvironment(
					&spb.EnvironmentRecord{
						GpuNvidia: []*spb.GpuNvidiaInfo{{Uuid: "GPU-a"}, {Uuid: "GPU-b"}},
					},
				)
			}
			t.Setenv("WANDB_X_PROVENANCE_REDACTION_KEY", tc.key)
			require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
			if tc.binding != "" {
				emitter.AddRecord(
					provenance.Record{
						Kind:        "binding",
						PayloadJSON: []byte(tc.binding),
						MonotonicNS: 1,
					},
				)
			}
			emitter.OnSample(
				&spb.StatsRecord{Item: []*spb.StatsItem{
					{Key: "gpu.0.gpu", ValueJson: "10"},
					{Key: "gpu.1.gpu", ValueJson: "85"},
				}},
				nil,
			)
			result := emitter.Drain()
			assert.Equal(t, tc.want, readManifest(t, dir).Capabilities["gpu_metrics"])
			if tc.environment {
				assert.Equal(t, tc.gaps, result.Quality.Gaps)
			}
		})
	}
}

func TestLevel1TransportEvidenceReachesTheManifestOnlyAtLevel1(t *testing.T) {
	record := `{"collector":"nccl_transport","status":"partial","reason":"configured_and_loaded",` +
		`"source":"proc_maps+nccl_env","transport":"tcpx","configured":"tcpx","loaded":"tcpx",` +
		`"confidence":"configured_and_loaded","nccl_env":{"NCCL_NET":"tcpx","NCCL_GPUDIRECTTCPX_FORCE_ACK":"0","NCCL_GPUDIRECTTCPX_SOCKET_IFNAME":"set"}}`
	for _, level := range []int{0, 1} {
		dir := t.TempDir()
		emitter := provenance.NewEmitter(
			&provenance.EmitterParams{
				FilesDir: dir,
				Host:     provenance.HostPaths{SysRoot: t.TempDir()},
			},
		)
		require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer", Level: level}))
		emitter.AddRecord(
			provenance.Record{Kind: "capability", PayloadJSON: []byte(record), MonotonicNS: 1},
		)
		emitter.OnSample(nil, nil)
		result := emitter.Drain()
		assert.Zero(t, result.Quality.RejectedRecords)
		manifest := readManifest(t, dir)
		require.NotNil(t, manifest.Platform)
		transport := manifest.Platform.Transport
		if level == 0 {
			assert.Equal(t, "unknown", transport.Name)
			continue
		}
		assert.Equal(t, "tcpx", transport.Name)
		assert.Equal(t, "configured_and_loaded", transport.Confidence)
		assert.Equal(t, "set", transport.Env["NCCL_GPUDIRECTTCPX_SOCKET_IFNAME"])
		assert.Equal(
			t,
			provenance.Capability{Status: "partial", Reason: "configured_and_loaded"},
			manifest.Capabilities["nccl_transport"],
		)
	}
}

func TestNCCLEnvironmentEvidenceRejectsInterfaceNamesAndUnlistedVariables(t *testing.T) {
	for _, env := range []string{
		`{"NCCL_GPUDIRECTTCPX_SOCKET_IFNAME":"eth1,eth2"}`,
		`{"NCCL_SOCKET_IFNAME":"set"}`,
		`{"NCCL_NET_PLUGIN":"/usr/local/tcpx/lib64/libnccl-net.so"}`,
	} {
		emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: t.TempDir()})
		require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer", Level: 1}))
		emitter.AddRecord(provenance.Record{
			Kind: "capability",
			PayloadJSON: []byte(
				`{"collector":"nccl_transport","status":"partial","nccl_env":` + env + `}`,
			),
			MonotonicNS: 1,
		})
		assert.EqualValues(t, 1, emitter.Drain().Quality.RejectedRecords, env)
	}
}

func TestExitReasonIsHonestForFailedAttemptsAndParentExit(t *testing.T) {
	dir := t.TempDir()
	failed := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir})
	require.NoError(t, failed.Start(provenance.StartConfig{WriterID: "writer", Attempt: 1}))
	failed.AddRecord(provenance.Record{
		Kind: "lifecycle",
		PayloadJSON: []byte(
			`{"event":"init_process_group","status":"partial","reason":"attempt_failed"}`,
		),
		MonotonicNS: 1,
	})
	failed.SetExit(1, "finish")
	failed.Drain()
	assert.Equal(t, &provenance.Exit{Code: 1, Reason: "attempt_failed"}, readManifest(t, dir).Exit)

	dir = t.TempDir()
	work := &exitWork{}
	orphan := provenance.NewEmitter(
		&provenance.EmitterParams{FilesDir: dir, WriterID: "writer", Work: work},
	)
	require.True(t, orphan.Handshake(&spb.ProvenanceStartRequest{ProtocolVersion: 2}).Accepted)
	provenance.Terminate(time.Second, 1)
	orphan.Drain()
	assert.Equal(t, &provenance.Exit{Code: 1, Reason: "parent_exited"}, readManifest(t, dir).Exit)
}

func TestGPUSampleKeysIgnoreLabelsAppliedAfterTheSample(t *testing.T) {
	dir := t.TempDir()
	now := time.Now()
	emitter := provenance.NewEmitter(
		&provenance.EmitterParams{FilesDir: dir, Now: func() time.Time { return now }},
	)
	emitter.SetEnvironment(&spb.EnvironmentRecord{GpuNvidia: []*spb.GpuNvidiaInfo{{Uuid: "GPU-b"}}})
	t.Setenv("WANDB_X_PROVENANCE_REDACTION_KEY", strings.Repeat("ab", 32))
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
	emitter.AddRecord(provenance.Record{
		Kind: "binding",
		PayloadJSON: []byte(
			`{"gpu_uuid_hmac":"gpu_uuid_3eb65075498508521b048895","status":"available"}`,
		),
		MonotonicNS: 1,
	})
	emitter.OnSample(nil, nil)
	sample := &spb.StatsRecord{Item: []*spb.StatsItem{{Key: "gpu.0.gpu", ValueJson: "85"}}}
	now = now.Add(time.Second)
	emitter.OnSample(sample, nil)
	sample.Item[0].Key += "/l:rank0"
	now = now.Add(15 * time.Second)
	emitter.OnSample(nil, nil)
	emitter.Drain()
	var keys []string
	for _, record := range chunkRecords(t, dir) {
		if values, ok := record["values"].(map[string]any); ok {
			for key := range values {
				keys = append(keys, key)
			}
		}
	}
	assert.Equal(t, []string{"gpu.gpu_uuid_3eb65075498508521b048895.gpu"}, keys)
}

func TestPrimaryMovesToANewerAttemptWhenItsManifestIsWritten(t *testing.T) {
	dir := t.TempDir()
	first := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir})
	require.NoError(t, first.Start(provenance.StartConfig{WriterID: "attempt-0", Primary: true}))
	first.Drain()
	retry := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir})
	require.NoError(
		t,
		retry.Start(provenance.StartConfig{WriterID: "attempt-1", Attempt: 1, Primary: true}),
	)
	data, err := os.ReadFile(filepath.Join(dir, "wandb-telemetry", "v2", "primary.json"))
	require.NoError(t, err)
	var pointer provenance.Primary
	require.NoError(t, json.Unmarshal(data, &pointer))
	assert.Equal(t, 1, pointer.Attempt)
	assert.Equal(t, "attempt-1", pointer.WriterID)
	assert.False(t, pointer.Finalized)
	assert.FileExists(t, filepath.Join(dir, pointer.Manifest))
	retry.Drain()
}
