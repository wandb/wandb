package artifacts_test

import (
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/artifacts"
)

type Marshallable struct {
	Junk string
}

func TestUtilFiles(t *testing.T) {
	data := Marshallable{"junk"}
	filename, digest, err := artifacts.WriteJsonToFileWithDigest(data)
	defer os.Remove(filename)
	assert.Equal(t, "T1eltpgz2/KgyAYJfrs4Sg==", digest)
	assert.FileExists(t, filename)
	assert.Nil(t, err)
}
