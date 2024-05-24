package server_test

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/watchertest"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/server"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

// testOptions is data used to configure a test.
type testOptions struct {
	// The files_dir run setting, as a slash-separated relative path.
	SlashFilesDir string

	// The _start_time run setting.
	StartTime float64

	// The Hostname to pass to the constructor.
	Hostname string
}

// testContext is a set of variables and functions available in each test.
type testContext struct {
	// Handler is the TBHandler being tested.
	Handler *server.TBHandler

	// FakeFileWatcher is the file watcher used by Handler.
	FakeFileWatcher *watchertest.FakeWatcher

	// EmittedRecords returns the records emitted so far by the handler.
	EmittedRecords func() []*service.Record

	// Path converts a slash/separated/relative/path into an absolute path.
	Path func(slashPath string) string

	// TouchFile creates a file given a slash/separated/relative/path.
	TouchFile func(slashPath string)

	// DeleteFile deletes a file given a slash/separated/relative/path.
	DeleteFile func(slashPath string)
}

func setupTest(t *testing.T, opts testOptions) testContext {
	t.Helper()

	fakeFileWatcher := watchertest.NewFakeWatcher()
	outChan := make(chan *service.Record, 100)

	tmpdir := t.TempDir()
	toPath := func(slashPath string) string {
		return filepath.Join(tmpdir, filepath.FromSlash(slashPath))
	}

	settings := &service.Settings{}
	if opts.SlashFilesDir != "" {
		settings.FilesDir = wrapperspb.String(toPath(opts.SlashFilesDir))
	}
	if opts.StartTime != 0 {
		settings.XStartTime = wrapperspb.Double(opts.StartTime)
	}

	handler := server.NewTBHandler(
		fakeFileWatcher,
		observability.NewNoOpLogger(),
		settings,
		outChan,
		opts.Hostname,
	)

	return testContext{
		Handler:         handler,
		FakeFileWatcher: fakeFileWatcher,
		EmittedRecords: func() []*service.Record {
			t.Helper()
			records := make([]*service.Record, 0)
			for {
				select {
				case rec, ok := <-outChan:
					if !ok {
						return records
					}
					records = append(records, rec)
				default:
					return records
				}
			}
		},
		Path: toPath,
		TouchFile: func(slashPath string) {
			t.Helper()
			path := toPath(slashPath)

			require.NoError(t, os.MkdirAll(filepath.Dir(path), os.ModePerm))
			require.NoError(t, os.WriteFile(path, []byte{}, syscall.S_IRUSR|syscall.S_IWUSR))
		},
		DeleteFile: func(slashPath string) {
			t.Helper()
			require.NoError(t, os.Remove(toPath(slashPath)))
		},
	}
}

func Test_FiltersFiles(t *testing.T) {
	type testCase struct {
		slashPath string
		emits     bool
	}

	cases := map[string]testCase{
		"good time and hostname": {
			"logs/train/events.out.tfevents.999.testhost.0.0", true,
		},
		"bad time": {
			"logs/train/events.out.tfevents.111.testhost.0.0", false,
		},
		"bad hostname": {
			"logs/train/events.out.tfevents.999.nothostname.0.0", false,
		},
		"outside root": {
			"elsewhere/train/events.out.tfevents.999.testhost.0.0", false,
		},
		"profile-empty": {
			"logs/train/events.out.tfevents.999.testhost.profile-empty", false,
		},
		"sagemaker": {
			"logs/train/events.out.tfevents.999.testhost.sagemaker-uploaded", false,
		},
	}

	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			ctx := setupTest(t, testOptions{
				StartTime:     555,
				SlashFilesDir: "runfiles",
				Hostname:      "testhost",
			})
			ctx.TouchFile(tc.slashPath)

			require.NoError(t,
				ctx.Handler.Handle(&service.TBRecord{
					LogDir:  ctx.Path("logs/train"),
					RootDir: ctx.Path("logs"),
					Save:    true,
				}))

			if tc.emits {
				assert.Len(t, ctx.EmittedRecords(), 1)
			} else {
				assert.Empty(t, ctx.EmittedRecords())
			}
		})
	}
}

func Test_SymlinksFile(t *testing.T) {
	ctx := setupTest(t, testOptions{SlashFilesDir: "runfiles"})
	ctx.TouchFile("logs/train/events.out.tfevents.123.hostname")

	require.NoError(t,
		ctx.Handler.Handle(&service.TBRecord{
			LogDir:  ctx.Path("logs/train"),
			RootDir: ctx.Path("logs"),
			Save:    true,
		}))

	assert.FileExists(t,
		ctx.Path("runfiles/train/events.out.tfevents.123.hostname"))
}

func Test_EmitsUploadRecordOnce(t *testing.T) {
	ctx := setupTest(t, testOptions{SlashFilesDir: "runfiles"})
	ctx.TouchFile("logs/train/events.out.tfevents.123.hostname")

	require.NoError(t,
		ctx.Handler.Handle(&service.TBRecord{
			LogDir:  ctx.Path("logs/train"),
			RootDir: ctx.Path("logs"),
			Save:    true,
		}))
	ctx.FakeFileWatcher.OnChange(ctx.Path(
		"logs/train/events.out.tfevents.123.hostname"))
	ctx.FakeFileWatcher.OnChange(ctx.Path(
		"logs/train/events.out.tfevents.123.hostname"))

	assert.Equal(t,
		[]*service.Record{
			{
				RecordType: &service.Record_Files{
					Files: &service.FilesRecord{
						Files: []*service.FilesItem{{
							Policy: service.FilesItem_END,
							Path:   filepath.Join("train", "events.out.tfevents.123.hostname"),
						}},
					},
				},
			},
		},
		ctx.EmittedRecords())
}

func Test_DetectsNewFiles(t *testing.T) {
	ctx := setupTest(t, testOptions{SlashFilesDir: "runfiles"})

	require.NoError(t,
		ctx.Handler.Handle(&service.TBRecord{
			LogDir:  ctx.Path("logs/train"),
			RootDir: ctx.Path("logs"),
			Save:    true,
		}))
	ctx.TouchFile("logs/train/events.out.tfevents.123.hostname")
	assert.NoFileExists(t,
		ctx.Path("runfiles/train/events.out.tfevents.123.hostname"))
	ctx.FakeFileWatcher.OnChange(ctx.Path(
		"logs/train/events.out.tfevents.123.hostname"))

	assert.FileExists(t,
		ctx.Path("runfiles/train/events.out.tfevents.123.hostname"))
}
