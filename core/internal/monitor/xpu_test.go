package monitor

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestXPU_StatsRequestIncludesThrottleReasonsOnlyWhenSet(t *testing.T) {
	on := NewXPU(context.Background(), nil, 123, []int32{0, 1}, true)
	assert.True(t, on.statsRequest().GetIncludeThrottleReasons())

	off := NewXPU(context.Background(), nil, 123, []int32{0, 1}, false)
	assert.False(t, off.statsRequest().GetIncludeThrottleReasons())
}
