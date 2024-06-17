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
	p.Writef("message %d", 2)

	assert.Equal(t,
		[]string{"message 1", "message 2"},
		p.Read())
}

func TestRateLimitedWrite(t *testing.T) {
	nowMilli := &atomic.Int64{}
	p := NewPrinter()
	p.getNow = func() time.Time { return time.UnixMilli(nowMilli.Load()) }

	p.AtMostEvery(time.Minute).Writef("hey there %d", 1)
	p.AtMostEvery(time.Minute).Writef("hey there %d", 2)
	p.AtMostEvery(time.Minute).Writef("hey there %d", 3)
	nowMilli.Add(time.Minute.Milliseconds())
	p.AtMostEvery(time.Minute).Writef("hey there %d", 4)
	p.AtMostEvery(time.Minute).Writef("hey there %d", 5)
	p.AtMostEvery(time.Minute).Writef("hey there %d", 6)

	assert.Equal(t,
		[]string{"hey there 1", "hey there 4"},
		p.Read())
}
