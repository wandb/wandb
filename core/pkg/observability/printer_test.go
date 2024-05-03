package observability

import (
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestReadAfterWrite(t *testing.T) {
	p := NewPrinter()

	p.Write("message 1")
	p.Write("message 2")

	assert.Equal(t,
		[]string{"message 1", "message 2"},
		p.Read())
}

func TestRateLimitedWrite(t *testing.T) {
	nowMilli := &atomic.Int64{}
	p := NewPrinter()
	p.getNow = func() time.Time { return time.UnixMilli(nowMilli.Load()) }

	p.AtMostEvery(time.Minute).Write("hey there") // first write
	p.AtMostEvery(time.Minute).Write("hey there") // ignored
	p.AtMostEvery(time.Minute).Write("hey there") // ignored
	nowMilli.Add(time.Minute.Milliseconds())
	p.AtMostEvery(time.Minute).Write("hey there") // second write
	p.AtMostEvery(time.Minute).Write("hey there") // ignored
	p.AtMostEvery(time.Minute).Write("hey there") // ignored

	assert.Equal(t,
		[]string{"hey there", "hey there"},
		p.Read())
}
