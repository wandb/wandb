package hashlib_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/lib/hashlib"
)

func TestEncode(t *testing.T) {
	encoded := hashlib.EncodeBytesAsHex([]byte(`junk`))
	assert.Equal(t, "6a756e6b", encoded)
}
