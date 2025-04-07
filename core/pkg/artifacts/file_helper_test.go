package artifacts_test

import (
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/pkg/artifacts"
)

type Marshallable struct {
	Junk string
}

func TestUtilFiles(t *testing.T) {
	data := Marshallable{"junk"}
	filename, digest, size, err := artifacts.WriteJSONToTempFileWithMetadata(data)
	defer func() {
		_ = os.Remove(filename)
	}()
	assert.Equal(t, "T1eltpgz2/KgyAYJfrs4Sg==", digest)
	assert.Equal(t, int64(15), size)
	assert.FileExists(t, filename)
	assert.Nil(t, err)
}
