package tensorboard_test

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/waitingtest"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

// testOptions is data used to configure a test.
type testOptions struct {
	// The files_dir run setting, as a slash-separated relative path.
	SlashFilesDir string
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

	outChan := make(chan *service.Record, 100)
	fileReadDleay := waitingtest.NewFakeDelay()

	tmpdir := t.TempDir()
	toPath := func(slashPath string) string {
		return filepath.Join(tmpdir, filepath.FromSlash(slashPath))
	}

	settings := &service.Settings{}
	if opts.SlashFilesDir != "" {
		settings.FilesDir = wrapperspb.String(toPath(opts.SlashFilesDir))
	}

	handler := tensorboard.NewTBHandler(tensorboard.Params{
		OutputRecords: outChan,
		Logger:        observability.NewNoOpLogger(),
		Settings:      settings,
		FileReadDelay: fileReadDleay,
	})

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
	ctx := setupTest(t, testOptions{SlashFilesDir: "runfiles"})
	ctx.TouchFile("logs/train/events.out.tfevents.123.hostname")

	ctx.Handler.Handle(&service.TBRecord{
		LogDir:  ctx.Path("logs/train"),
		RootDir: ctx.Path("logs"),
		Save:    true,
	})
	ctx.Handler.Finish()

	assert.FileExists(t,
		ctx.Path("runfiles/train/events.out.tfevents.123.hostname"))
}
