package monitor

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestEnvironmentRecordDropsExcludedMetadata(t *testing.T) {
	sm := (&SystemMonitorFactory{
		Logger: observabilitytest.NewTestLogger(t),
		Settings: settings.From(&spb.Settings{
			XDisableStats:   wrapperspb.Bool(true),
			ExcludeMetadata: &spb.ListStringValue{Value: []string{"executable"}},
		}),
		XPUResourceManager: NewXPUResourceManager(false),
	}).New(runworktest.New())

	env := sm.environmentRecord(&spb.EnvironmentRecord{
		Os:         "macOS",
		Executable: "/usr/bin/python",
	}).GetEnvironment()

	assert.Equal(t, "macOS", env.GetOs())
	assert.Empty(t, env.GetExecutable())
}
