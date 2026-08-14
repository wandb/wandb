package transactionlog

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
)

// TestWandbStoreVersion pins wandbStoreVersion as the mechanism that makes a
// breaking .wandb format change fail loudly in old clients instead of
// silently losing data: leveldb.Reader.VerifyWandbHeader rejects a header
// whose version byte doesn't match what the reader expects (see
// core/pkg/leveldb/record_internal_test.go's TestVerifyWandbHeader_*).
//
// wandb PR #12110 changed what a non-shared HistoryRecord looks like on
// disk (see the historystep_compat_test.go / golden-corpus format guards)
// without bumping this constant -- see phase 6 of the compat plan. This
// test does not take a position on whether that was correct; it pins the
// current value so that a future bump is a deliberate, visible edit here,
// not an incidental one.
func TestWandbStoreVersion(t *testing.T) {
	require.Equal(t, byte(0), byte(wandbStoreVersion))

	path := filepath.Join(t.TempDir(), "version.wandb")
	w, err := OpenWriter(path)
	require.NoError(t, err)
	require.NoError(t, w.Close())

	contents, err := os.ReadFile(path)
	require.NoError(t, err)
	require.GreaterOrEqual(t, len(contents), 7, "file too short for a header")

	require.Equal(t, byte(wandbStoreVersion), contents[6],
		"header byte 6 is the format version leveldb.Reader.VerifyWandbHeader"+
			" checks; it must match wandbStoreVersion")
}
