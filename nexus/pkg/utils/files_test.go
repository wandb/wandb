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
	filename, digest, err := WriteJsonToFileWithDigest(data)
	defer os.Remove(filename)
	assert.Equal(t, "T1eltpgz2/KgyAYJfrs4Sg==", digest)
	assert.FileExists(t, filename)
	assert.Nil(t, err)
}
