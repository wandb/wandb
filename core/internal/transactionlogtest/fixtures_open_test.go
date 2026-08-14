package transactionlogtest

import (
	"errors"
	"io"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/transactionlog"
)

// TestReader_AcceptsAllCommittedFixtures opens and fully reads every
// committed golden fixture under tests/assets/compat_logs.
//
// This is the other half of transactionlog's TestWandbStoreVersion: a
// version bump can't land without a read path that still accepts every
// format this repo claims to support, old and new alike.
func TestReader_AcceptsAllCommittedFixtures(t *testing.T) {
	for _, c := range goldenCorpus {
		t.Run(c.Name, func(t *testing.T) {
			r, err := transactionlog.OpenReader(
				GoldenLogPath(t, c.Name), observabilitytest.NewTestLogger(t))
			require.NoError(t, err)
			defer r.Close()

			var count int
			for {
				_, err := r.Read()
				if err != nil {
					require.Truef(t, errors.Is(err, io.EOF),
						"unexpected error reading %q: %v", c.Name, err)
					break
				}
				count++
			}

			assert.Equal(t, len(c.Records), count,
				"expected every record in goldenCorpus to be readable back")
		})
	}
}
