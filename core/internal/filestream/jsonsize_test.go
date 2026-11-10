package filestream

import (
	"encoding/json"
	"math/rand/v2"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestJSONStringLen_MatchesEncodingJSON(t *testing.T) {
	cases := []string{
		"",
		`{"_step":1,"loss":0.5}`,
		"tab\tnewline\nreturn\rbackspace\bformfeed\f",
		`quote" backslash\ <html>&amp;`,
		"control\x01\x1f",
		"unicode héllo 世界 🎉",
		"separators    ",
		"invalid \xff\xfe utf8 \xe4\xb8",
	}
	for _, s := range cases {
		encoded, err := json.Marshal(s)
		require.NoError(t, err)
		assert.Equal(t, len(encoded), jsonStringLen(s), "%q", s)
	}
}

func TestJSONStringLen_MatchesEncodingJSONOnRandomBytes(t *testing.T) {
	rng := rand.New(rand.NewPCG(1, 2))
	for range 2000 {
		b := make([]byte, rng.IntN(64))
		for i := range b {
			b[i] = byte(rng.IntN(256))
		}
		s := string(b)

		encoded, err := json.Marshal(s)
		require.NoError(t, err)
		require.Equal(t, len(encoded), jsonStringLen(s), "%q", s)
	}
}
