package leet

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestFeatureName_DerivedFromHandlerMethod(t *testing.T) {
	assert.Equal(t,
		"run.toggle_metrics_grid",
		featureName((*Run).handleToggleMetricsGrid))
}
