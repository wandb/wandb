package runsync

import (
	"path/filepath"

	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

// MakeSyncSettings creates the settings for syncing a run.
//
// Settings are not stored in the transaction log, but some settings are
// important for correctly interpreting it, such as files_dir which is the
// base path for the relative file paths in the transaction log.
func MakeSyncSettings(
	globalSettings *spb.Settings,
	wandbFile string,
) *settings.Settings {
	syncSettings := proto.CloneOf(globalSettings)

	// Syncing ignores offline mode.
	syncSettings.XOffline = wrapperspb.Bool(false)

	// This determines files_dir.
	syncSettings.SyncDir = wrapperspb.String(filepath.Dir(wandbFile))

	return settings.From(syncSettings)
}
