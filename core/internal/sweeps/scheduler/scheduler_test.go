package scheduler

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

// fakeClock lets tests control the scheduler's notion of now and fires
// every timer immediately so failure slowdowns cost no test time.
type fakeClock struct {
	now time.Time
}

func (c *fakeClock) Now() time.Time { return c.now }

func (c *fakeClock) NewTimer(time.Duration) (<-chan time.Time, func()) {
	fire := make(chan time.Time, 1)
	fire <- time.Time{}
	return fire, func() {}
}

var (
	_ Clock = realClock{}
	_ Clock = (*fakeClock)(nil)
)

func TestRealClockNowIsWallClockTime(t *testing.T) {
	before := time.Now()
	now := realClock{}.Now()
	after := time.Now()

	assert.False(t, now.Before(before))
	assert.False(t, now.After(after))
}

func TestRealClockNewTimerFiresAfterTheDuration(t *testing.T) {
	fire, stop := realClock{}.NewTimer(10 * time.Millisecond)
	defer stop()

	select {
	case <-fire:
	case <-time.After(time.Second):
		t.Fatal("timer did not fire")
	}
}

func TestFakeClockNewTimerFiresImmediately(t *testing.T) {
	clock := &fakeClock{now: time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)}

	fire, stop := clock.NewTimer(time.Hour)
	defer stop()

	select {
	case <-fire:
	default:
		t.Fatal("expected the fake timer to have already fired")
	}
}
