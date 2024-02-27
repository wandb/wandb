package utils

import (
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
)

type Marshallable struct {
	Junk string
}

func TestUtilFiles(t *testing.T) {
	data := Marshallable{"junk"}
	filename, digest, size, err := WriteJsonToFileWithDigest(data)
	defer os.Remove(filename)
	assert.Equal(t, "T1eltpgz2/KgyAYJfrs4Sg==", digest)
	assert.Equal(t, int64(15), size)
	assert.FileExists(t, filename)
	assert.Nil(t, err)
}
