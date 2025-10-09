package iterator

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestNoopRowIterator_Next_ReturnsFalse(t *testing.T) {
	iter := &NoopRowIterator{}

	hasNext, err := iter.Next()

	assert.False(t, hasNext)
	assert.NoError(t, err)
}

func TestNoopRowIterator_Value_ReturnsEmptyKeyValueList(t *testing.T) {
	iter := &NoopRowIterator{}

	value := iter.Value()

	assert.Empty(t, value)
}
