package utils

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestEncode(t *testing.T) {
	encoded := EncodeBytesAsHex([]byte(`junk`))
	assert.Equal(t, "6a756e6b", encoded)
}
