package utils

import (
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestEncode(t *testing.T) {
	encoded := EncodeBytesAsHex([]byte(`junk`))
	assert.Equal(t, "6a756e6b", encoded)
}

func TestHexB64RoundTrip(t *testing.T) {
	b64hash, err := ComputeB64MD5([]byte(`some data`))
	assert.NoError(t, err)

	hexHash, err := B64ToHex(b64hash)
	assert.NoError(t, err)
	alsoB64, err := HexToB64(hexHash)
	assert.NoError(t, err)
	assert.Equal(t, b64hash, alsoB64)
	assert.NotEqual(t, b64hash, hexHash)
}

func TestHashValidity(t *testing.T) {
	b64hash, err := ComputeB64MD5([]byte(`test`))
	assert.NoError(t, err)

	hexHash, err := B64ToHex(b64hash)
	assert.NoError(t, err)

	// Hash according to Python's hashlib.md5(b"test").hexdigest()
	assert.Equal(t, "098f6bcd4621d373cade4e832627b4f6", hexHash)
}

func TestVerifyDataHash(t *testing.T) {
	b64md5, err := ComputeB64MD5([]byte(`foobar`))
	assert.NoError(t, err)

	assert.True(t, VerifyDataHash([]byte(`foobar`), b64md5))

	otherB64md5, err := ComputeB64MD5([]byte(`foobar\0`))
	assert.NoError(t, err)
	assert.False(t, VerifyDataHash([]byte(`foobar`), otherB64md5))
}

func TestVerifyFileHash(t *testing.T) {
	testFile, err := os.CreateTemp("", "")
	assert.NoError(t, err)
	defer testFile.Close()
	_, err = testFile.Write([]byte(`foobar`))
	assert.NoError(t, err)

	b64md5, err := ComputeB64MD5([]byte(`foobar`))
	assert.NoError(t, err)

	assert.True(t, VerifyFileHash(testFile.Name(), b64md5))
}
