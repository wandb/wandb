package runsync_test

import (
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/runsync"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func Test_DoSync_NotPrepped(t *testing.T) {
	m := runsync.NewRunSyncManager()
	request := &spb.ServerSyncRequest{Id: "bad-id"}

	response := m.DoSync(request)

	assert.Len(t, response.Messages, 1)
	assert.Equal(t,
		spb.ServerSyncMessage_SEVERITY_ERROR,
		response.Messages[0].Severity)
	assert.Equal(t,
		"Internal error: operation unknown or already started: bad-id",
		response.Messages[0].Content)
}
