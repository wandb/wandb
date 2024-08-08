package observability_test

import (
	"fmt"
	"io/fs"
	"os"
	"testing"

	"github.com/spf13/afero"
	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/pkg/observability"
)

type AferoFs struct {
	Afs afero.Fs
}

func (afs AferoFs) MkdirAll(path string, perm os.FileMode) error {
	return afs.Afs.MkdirAll(path, perm)
}

func (afs AferoFs) OpenFile(name string, flag int, perm os.FileMode) (fs.File, error) {
	return afs.Afs.OpenFile(name, flag, perm)
}

func TestGetLoggerPath(t *testing.T) {
	fs := AferoFs{Afs: afero.NewMemMapFs()}

	os.Setenv("WANDB_CACHE_DIR", "/tmp/wandb")
	defer os.Unsetenv("WANDB_CACHE_DIR")

	file, err := observability.GetLoggerPathFS(fs)
	assert.NoError(t, err)
	assert.NotNil(t, file)

	// Type assert to afero.File to access the Name method
	aferoFile, ok := file.(afero.File)
	assert.True(t, ok, "File should be of type afero.File")

	// Assert file was created
	_, err = fs.Afs.Stat(aferoFile.Name())
	assert.NoError(t, err)

	aferoFile.Close()
}

func TestGetLoggerPath_MkdirFail(t *testing.T) {
	fs := AferoFs{Afs: afero.NewReadOnlyFs(afero.NewMemMapFs())}

	os.Setenv("WANDB_CACHE_DIR", "/tmp/wandb")
	defer os.Unsetenv("WANDB_CACHE_DIR")

	_, err := observability.GetLoggerPathFS(fs)
	assert.Error(t, err, "Expected an error when failing to create a directory")
}

type FailOpenFileFs struct {
	afero.Fs
}

func (fs FailOpenFileFs) OpenFile(name string, flag int, perm os.FileMode) (afero.File, error) {
	return nil, fmt.Errorf("simulated open file error")
}

func TestGetLoggerPath_OpenFileFail(t *testing.T) {
	fs := AferoFs{Afs: FailOpenFileFs{afero.NewMemMapFs()}}

	os.Setenv("WANDB_CACHE_DIR", "/tmp/wandb")
	defer os.Unsetenv("WANDB_CACHE_DIR")

	_, err := observability.GetLoggerPathFS(fs)
	assert.Error(t, err, "Expected an error when failing to open a file")
}
