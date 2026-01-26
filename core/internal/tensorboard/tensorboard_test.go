package tensorboard_test

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/waitingtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// testOptions is data used to configure a test.
type testOptions struct {
	// The files_dir run setting, as a slash-separated relative path.
	SlashSyncDir string
}

// testContext is a set of variables and functions available in each test.
type testContext struct {
	// Handler is the TBHandler being tested.
	Handler *tensorboard.TBHandler

	// Path converts a slash/separated/relative/path into an absolute path.
	Path func(slashPath string) string

	// TouchFile creates a file given a slash/separated/relative/path.
	TouchFile func(slashPath string)
}

func setupTest(t *testing.T, opts testOptions) testContext {
	t.Helper()

	runWork := runworktest.New()
	fileReadDelay := waitingtest.NewFakeDelay()

	tmpdir := t.TempDir()
	toPath := func(slashPath string) string {
		return filepath.Join(tmpdir, filepath.FromSlash(slashPath))
	}

	settingsProto := &spb.Settings{}
	if opts.SlashSyncDir != "" {
		settingsProto.SyncDir = wrapperspb.String(toPath(opts.SlashSyncDir))
	}
	s := settings.From(settingsProto)

	factory := tensorboard.TBHandlerFactory{
		Logger:   observabilitytest.NewTestLogger(t),
		Settings: s,
	}
	handler := factory.New(runWork, fileReadDelay)

	return testContext{
		Handler: handler,
		Path:    toPath,
		TouchFile: func(slashPath string) {
			t.Helper()
			path := toPath(slashPath)

			require.NoError(t, os.MkdirAll(filepath.Dir(path), os.ModePerm))
			require.NoError(t, os.WriteFile(path, []byte{}, syscall.S_IRUSR|syscall.S_IWUSR))
		},
	}
}

func Test_SymlinksFile(t *testing.T) {
	ctx := setupTest(t, testOptions{SlashSyncDir: "my-run"})
	ctx.TouchFile("logs/train/events.out.tfevents.123.hostname")

	require.NoError(t,
		ctx.Handler.Handle(&spb.TBRecord{
			LogDir:  ctx.Path("logs/train"),
			RootDir: ctx.Path("logs"),
			Save:    true,
		}))
	ctx.Handler.Finish()

	assert.FileExists(t,
		ctx.Path("my-run/files/train/events.out.tfevents.123.hostname"))
}
