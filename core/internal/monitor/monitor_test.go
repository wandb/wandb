package monitor_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func newTestSystemMonitor(
	t *testing.T,
	resourceManager *monitor.SymonResourceManager,
	wbSettings *settings.Settings,
) *monitor.SystemMonitor {
	t.Helper()

	factory := &monitor.SystemMonitorFactory{
		Logger:               observabilitytest.NewTestLogger(t),
		Settings:             wbSettings,
		SymonResourceManager: resourceManager,
	}

	return factory.New(runworktest.New())
}

func TestSystemMonitor(t *testing.T) {
	resourceManager := monitor.NewSymonResourceManager(false)

	t.Run("Start subscribes", func(t *testing.T) {
		sm := newTestSystemMonitor(t, resourceManager, settings.New())
		defer sm.Finish()

		sm.Start()

		assert.True(t, sm.TestOnlyIsSubscribed())
	})

	t.Run("Pause unsubscribes", func(t *testing.T) {
		sm := newTestSystemMonitor(t, resourceManager, settings.New())
		defer sm.Finish()

		sm.Start()
		sm.Pause()

		assert.False(t, sm.TestOnlyIsSubscribed())
	})

	t.Run("Paused Start does not subscribe", func(t *testing.T) {
		sm := newTestSystemMonitor(t, resourceManager, settings.New())
		defer sm.Finish()

		sm.Pause()
		sm.Start()

		assert.False(t, sm.TestOnlyIsSubscribed())
	})

	t.Run("Resume resubscribes", func(t *testing.T) {
		sm := newTestSystemMonitor(t, resourceManager, settings.New())
		defer sm.Finish()

		sm.Pause()
		sm.Start()
		sm.Resume()

		assert.True(t, sm.TestOnlyIsSubscribed())
	})

	t.Run("does not subscribe if x_disable_stats", func(t *testing.T) {
		sm := newTestSystemMonitor(t, resourceManager, settings.From(
			&spb.Settings{XDisableStats: wrapperspb.Bool(true)},
		))
		defer sm.Finish()

		sm.Start()
		sm.Resume()

		assert.False(t, sm.TestOnlyIsSubscribed())
	})

	t.Run("does not subscribe if x_disable_machine_info", func(t *testing.T) {
		sm := newTestSystemMonitor(t, resourceManager, settings.From(
			&spb.Settings{XDisableMachineInfo: wrapperspb.Bool(true)},
		))
		defer sm.Finish()

		sm.Start()
		sm.Resume()

		assert.False(t, sm.TestOnlyIsSubscribed())
	})
}
