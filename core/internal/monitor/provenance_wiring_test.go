package monitor

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observabilitytest"
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
	final := monitor.DrainProvenance()
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
