package runsync_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/runsync"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestMakeSyncSettings_ClearsClientOnlySettings(t *testing.T) {
	syncSettings := runsync.MakeSyncSettings(
		&spb.Settings{
			XOffline:      wrapperspb.Bool(true),
			FinishTimeout: wrapperspb.Double(60),
			InitTimeout:   wrapperspb.Double(90),
		},
		"run-abc123.wandb",
	)

	assert.False(t, syncSettings.IsOffline())
	assert.Zero(t, syncSettings.GetFinishTimeout())
	assert.Zero(t, syncSettings.GetInitTimeout())
}
