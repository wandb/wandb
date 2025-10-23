package golden

import (
	"bytes"
	"flag"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/aymanbagabas/go-udiff"
)

var update = flag.Bool("update", false, "update .golden files")

// RequireEqual is a helper function to assert the given output is
// the expected from the golden files, printing its diff in case it is not.
//
// You can update the golden files by running your tests with the -update flag.
func RequireEqual(tb testing.TB, out []byte) {
	RequireEqualEscape(tb, out, false)
}

// RequireEqualEscape is a helper function to assert the given output is
// the expected from the golden files, printing its diff in case it is not.
func RequireEqualEscape(tb testing.TB, out []byte, escapes bool) {
	tb.Helper()

	out = fixLineEndings(out)

	golden := filepath.Join("testdata", tb.Name()+".golden")
	if *update {
		if err := os.MkdirAll(filepath.Dir(golden), 0o755); err != nil { //nolint: gomnd
			tb.Fatal(err)
		}
		if err := os.WriteFile(golden, out, 0o600); err != nil { //nolint: gomnd
			tb.Fatal(err)
		}
	}

	goldenBts, err := os.ReadFile(golden)
	if err != nil {
		tb.Fatal(err)
	}

	goldenBts = fixLineEndings(goldenBts)
	goldenStr := string(goldenBts)
	outStr := string(out)
	if escapes {
		goldenStr = escapesSeqs(goldenStr)
		outStr = escapesSeqs(outStr)
	}

	diff := udiff.Unified("golden", "run", goldenStr, outStr)
	if diff != "" {
		tb.Fatalf("output does not match, expected:\n\n%s\n\ngot:\n\n%s\n\ndiff:\n\n%s", goldenStr, outStr, diff)
	}
}

func fixLineEndings(in []byte) []byte {
	return bytes.ReplaceAll(in, []byte("\r\n"), []byte{'\n'})
}

func escapesSeqs(in string) string {
	s := strings.Split(in, "\n")
	for i, l := range s {
		q := strconv.Quote(l)
		q = strings.TrimPrefix(q, `"`)
		q = strings.TrimSuffix(q, `"`)
		s[i] = q
	}
	return strings.Join(s, "\n")
}
