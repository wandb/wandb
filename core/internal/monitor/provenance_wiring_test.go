package monitor

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/provenance"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestProvenanceStartRejectsProtocolMismatch(t *testing.T) {
	var monitor *SystemMonitor
	response := monitor.StartProvenance(&spb.ProvenanceStartRequest{ProtocolVersion: 99})
	assert.False(t, response.Accepted)
	assert.Equal(t, uint32(2), response.ProtocolVersion)
	assert.Equal(t, "protocol_mismatch", response.Reason)
}

func TestProvenanceDisabledHasNoEmitter(t *testing.T) {
	factory := SystemMonitorFactory{
		Logger:   observabilitytest.NewTestLogger(t),
		Settings: settings.From(&spb.Settings{XDisableStats: wrapperspb.Bool(true)}),
	}
	monitor := factory.New(runworktest.New())
	assert.Nil(t, monitor.provenance)
	assert.Equal(
		t,
		"disabled",
		monitor.StartProvenance(&spb.ProvenanceStartRequest{ProtocolVersion: 2}).Reason,
	)
}

func TestProvenanceUsesCoreWriterIdentity(t *testing.T) {
	work := runworktest.New()
	factory := SystemMonitorFactory{
		Logger: observabilitytest.NewTestLogger(t),
		Settings: settings.From(
			&spb.Settings{
				XProvenanceLevel: wrapperspb.Int32(0),
				SyncDir:          wrapperspb.String(t.TempDir()),
			},
		),
		XPUResourceManager: NewXPUResourceManager(false),
		WriterID:           "session-distinct",
	}
	monitor := factory.New(work)
	response := monitor.StartProvenance(
		&spb.ProvenanceStartRequest{
			ProtocolVersion: 2,
			Level:           0,
			Rank:            0,
			Primary:         true,
			IdentityJson:    []byte(`{"world_size":8}`),
		},
	)
	require.True(t, response.Accepted, response.Reason)
	assert.Equal(t, "session-distinct", response.WriterId)
	require.Eventually(
		t,
		func() bool { return len(work.AllRecords()) > 0 },
		5*time.Second,
		10*time.Millisecond,
	)
	monitor.SetProvenanceRecord(
		&spb.ProvenanceRecord{Kind: "step", PayloadJson: []byte(`{"step":1}`), MonotonicNs: 1},
	)
	final := monitor.DrainProvenance(0)
	require.NotEmpty(t, final)
	for _, record := range final {
		for _, file := range record.GetFiles().GetFiles() {
			assert.Contains(t, file.Path, "wandb-telemetry/v2/")
			assert.NotContains(t, file.Path, "rank0")
		}
	}
	monitor.cancel()
}

func TestProvenanceRejectsLevelMismatch(t *testing.T) {
	factory := SystemMonitorFactory{
		Logger: observabilitytest.NewTestLogger(t),
		Settings: settings.From(
			&spb.Settings{
				XProvenanceLevel: wrapperspb.Int32(0),
				SyncDir:          wrapperspb.String(t.TempDir()),
			},
		),
		XPUResourceManager: NewXPUResourceManager(false),
		WriterID:           "writer",
	}
	monitor := factory.New(runworktest.New())
	defer monitor.cancel()
	assert.Equal(
		t,
		"level_mismatch",
		monitor.StartProvenance(&spb.ProvenanceStartRequest{ProtocolVersion: 2, Level: 1}).Reason,
	)
}

type fakeXPU struct{ environment *spb.EnvironmentRecord }

func (f fakeXPU) Sample() (*spb.StatsRecord, error) { return nil, nil }

func (f fakeXPU) Probe(context.Context) *spb.EnvironmentRecord { return f.environment }

func TestProvenanceReceivesTheXPUEnvironmentOnEveryWriter(t *testing.T) {
	key := strings.Repeat("ab", 32)
	t.Setenv("WANDB_X_PROVENANCE_REDACTION_KEY", key)
	decoded, err := hex.DecodeString(key)
	require.NoError(t, err)
	gpu, _ := provenance.NewRedactor(decoded).Pseudonym("gpu_uuid", "GPU-bound")
	for _, primary := range []bool{true, false} {
		dir := t.TempDir()
		factory := SystemMonitorFactory{
			Logger: observabilitytest.NewTestLogger(t),
			Settings: settings.From(
				&spb.Settings{
					XProvenanceLevel: wrapperspb.Int32(0),
					SyncDir:          wrapperspb.String(dir),
					XPrimary:         wrapperspb.Bool(primary),
				},
			),
			XPUResourceManager: NewXPUResourceManager(false),
			WriterID:           "writer",
		}
		monitor := factory.New(runworktest.New())
		xpu := fakeXPU{&spb.EnvironmentRecord{
			GpuNvidia: []*spb.GpuNvidiaInfo{{Uuid: "GPU-bound", Name: "NVIDIA A100-SXM4-40GB"}},
		}}
		monitor.xpu = xpu
		monitor.resources = []*monitoredResource{{Resource: xpu}}
		require.True(t, monitor.StartProvenance(
			&spb.ProvenanceStartRequest{
				ProtocolVersion: 2,
				Primary:         primary,
				IdentityJson:    []byte(`{}`),
			},
		).Accepted)
		monitor.SetProvenanceRecord(&spb.ProvenanceRecord{
			Kind:        "binding",
			PayloadJson: []byte(`{"gpu_uuid_hmac":"` + gpu + `","status":"available"}`),
			MonotonicNs: 1,
		})
		if primary {
			monitor.probeResources()
		} else {
			monitor.Probe()
			monitor.wg.Wait()
		}
		monitor.DrainProvenance(3)
		monitor.cancel()
		data, err := os.ReadFile(
			filepath.Join(dir, "files", "wandb-telemetry", "v2", "manifest", "writer.json"),
		)
		require.NoError(t, err)
		var manifest struct {
			Device       *provenance.Device               `json:"device"`
			Capabilities map[string]provenance.Capability `json:"capabilities"`
			Exit         *provenance.Exit                 `json:"exit"`
		}
		require.NoError(t, json.Unmarshal(data, &manifest))
		require.NotNil(t, manifest.Device, "primary=%v", primary)
		assert.Equal(t, "NVIDIA A100-SXM4-40GB", manifest.Device.Name)
		assert.Equal(
			t,
			provenance.Capability{Status: "available"},
			manifest.Capabilities["gpu_metrics"],
		)
		assert.Equal(t, &provenance.Exit{Code: 3, Reason: "finish"}, manifest.Exit)
	}
}
