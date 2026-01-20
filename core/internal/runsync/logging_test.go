package runsync_test

import (
	"os"
	"path/filepath"
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/runsync"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestOpenDebugSyncLogFile(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		// synctest time starts at 2000-01-01 at midnight UTC.
		// Wait until 2000-01-02 at 3:04:05 for a more reliable assertion.
		// Set TZ to UTC so that time.Now() uses UTC and not the local zone.
		t.Setenv("TZ", "UTC")
		time.Sleep(27*time.Hour + 4*time.Minute + 5*time.Second)

		// Test that OpenDebugSyncLogFile creates the directory.
		wandbDir := filepath.Join(t.TempDir(), "my-dir", "wandb")
		settings := settings.From(&spb.Settings{
			WandbDir: wrapperspb.String(wandbDir),
		})

		file, err := runsync.OpenDebugSyncLogFile(settings)
		require.NoError(t, err)
		require.NotNil(t, file)
		file.Close()

		assert.Equal(t,
			"debug-sync.20000102.030405.log",
			filepath.Base((*os.File)(file).Name()))
	})
}
