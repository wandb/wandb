package provenance_test

import (
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/provenance"
)

func TestPCIPseudonymIsTheSameForNVMLAndSysfsForms(t *testing.T) {
	redactor := provenance.NewRedactor([]byte(strings.Repeat("k", 32)))
	pseudonym := func(raw string) string {
		value, ok := redactor.Pseudonym("pci", raw)
		assert.True(t, ok)
		return value
	}
	for canonical, forms := range map[string][]string{
		"0000:3b:00.0":  {"00000000:3B:00.0", "0000:3B:00.0", "3b:00.0", " 0000:3b:00.0\n"},
		"0000:00:04.0":  {"00000000:00:04.0", "00:04.0"},
		"10000:01:1f.7": {"00010000:01:1F.7"},
	} {
		for _, form := range forms {
			assert.Equal(t, pseudonym(canonical), pseudonym(form), form)
		}
	}
	assert.NotEqual(t, pseudonym("0000:3b:00.0"), pseudonym("0000:3b:00.1"))
	assert.NotEqual(t, pseudonym("not-a-pci-address"), pseudonym("0000:3b:00.0"))
	assert.NotEqual(t, pseudonym("0000:3b:20.0"), pseudonym("0000:3b:00.0"))
}

func TestOnlyPCIPseudonymsAreCanonicalized(t *testing.T) {
	redactor := provenance.NewRedactor([]byte(strings.Repeat("k", 32)))
	upper, _ := redactor.Pseudonym("topology", "00000000:3B:00.0")
	lower, _ := redactor.Pseudonym("topology", "0000:3b:00.0")
	assert.NotEqual(t, upper, lower)
}
