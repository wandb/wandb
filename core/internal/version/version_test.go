package version_test

import (
	"fmt"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/version"
)

func TestCompare_NotEqual(t *testing.T) {
	testCases := []struct {
		V1, V2 string // lesser followed by greater
	}{
		{"invalid", "1.2.3"},

		{"0.30.1", "1.0.0"},
		{"0.30.1", "0.31.0"},
		{"0.30.1", "0.30.2"},

		{"0.30.1.dev1", "0.30.1"},
		{"0.30.1.dev1", "0.30.1rc20260901"},

		{"0.30.1rc20260901", "0.30.1"},
	}

	for _, tc := range testCases {
		name := fmt.Sprintf("%s < %s", tc.V1, tc.V2)
		t.Run(name, func(t *testing.T) {
			assert.Negative(t, version.Compare(tc.V1, tc.V2))
			assert.Positive(t, version.Compare(tc.V2, tc.V1))
		})
	}
}

func TestCompare_Equal(t *testing.T) {
	testCases := []struct {
		V1, V2 string
	}{
		{"invalid", "invalid"},
		{"1.2.3", "1.2.3"},
		{"1.2.3", "1.2.3+commithash"},

		{"1.2.3.dev1", "1.2.3.dev2"},
		{"1.2.3.dev1", "1.2.3rc.dev1"},
		{"1.2.3.dev1", "1.2.3.dev1+commithash"},

		{"1.2.3rc1", "1.2.3rc2"},
	}

	for _, tc := range testCases {
		name := fmt.Sprintf("%s ~ %s", tc.V1, tc.V2)
		t.Run(name, func(t *testing.T) {
			assert.Zero(t, version.Compare(tc.V1, tc.V2))
		})
	}
}

func TestPyPI(t *testing.T) {
	assert.Equal(t, "invalid", version.PyPI("invalid"))
	assert.Equal(t, "1.2.3", version.PyPI("1.2.3+xyz"))
	assert.Equal(t, "1.2.3rc1", version.PyPI("1.2.3rc1+xyz"))
	assert.Equal(t, "1.2.3.dev1", version.PyPI("1.2.3.dev1+xyz"))
}
