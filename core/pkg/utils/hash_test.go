package utils

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestEncode(t *testing.T) {
	encoded := EncodeBytesAsHex([]byte(`junk`))
	assert.Equal(t, "6a756e6b", encoded)
}

func TestHexToB64(t *testing.T) {
	data := "6a756e6b"
	expected := "anVuaw=="
	result, err := HexToB64(data)
	assert.NoError(t, err)
	assert.Equal(t, expected, result)
}