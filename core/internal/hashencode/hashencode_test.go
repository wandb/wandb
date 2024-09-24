package hashencode_test

import (
	"encoding/hex"
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/hashencode"
)

func TestHexB64RoundTrip(t *testing.T) {
	b64hash := hashencode.ComputeB64MD5([]byte(`some data`))

	hexHash, err := hashencode.B64ToHex(b64hash)
	assert.NoError(t, err)
	alsoB64, err := hashencode.HexToB64(hexHash)
	assert.NoError(t, err)
	assert.Equal(t, b64hash, alsoB64)
	assert.NotEqual(t, b64hash, hexHash)
}

func TestHashValidity(t *testing.T) {
	b64hash := hashencode.ComputeB64MD5([]byte(`test`))

	hexHash, err := hashencode.B64ToHex(b64hash)
	assert.NoError(t, err)

	// Hash according to Python's hashlib.md5(b"test").hexdigest()
	assert.Equal(t, "098f6bcd4621d373cade4e832627b4f6", hexHash)
}

func TestVerifyFileB64MD5(t *testing.T) {
	testFile, err := os.CreateTemp("", "")
	assert.NoError(t, err)
	defer testFile.Close()
	_, err = testFile.Write([]byte(`foobar`))
	assert.NoError(t, err)

	b64md5 := hashencode.ComputeB64MD5([]byte(`foobar`))
	assert.True(t, hashencode.VerifyFileB64MD5(testFile.Name(), b64md5))
}

func TestComputeHexMD5(t *testing.T) {
	data := []byte(`example data`)
	expectedHexMD5 := "5c71dbb287630d65ca93764c34d9aa0d"

	hexMD5 := hashencode.ComputeHexMD5(data)
	assert.Equal(t, expectedHexMD5, hexMD5)
}

func TestComputeSHA256(t *testing.T) {
	data := []byte(`example data`)
	expectedSHA256 := "44752f37272e944fd2c913a35342eaccdd1aaf189bae50676b301ab213fc5061"

	hexSHA256 := hex.EncodeToString(hashencode.ComputeSHA256(data))
	assert.Equal(t, expectedSHA256, hexSHA256)
}
