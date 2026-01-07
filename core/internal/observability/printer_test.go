package observability

import (
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestReadAfterWrite(t *testing.T) {
	p := NewPrinter()

	p.Infof("message %d", 1)
	p.Warnf("message %d", 2)
	p.Errorf("message %d", 3)

	assert.Equal(t,
		[]PrinterMessage{
			{Info, "message 1"},
			{Warning, "message 2"},
			{Error, "message 3"},
		},
		p.Read())
}

func TestRateLimitedWrite(t *testing.T) {
	nowMilli := &atomic.Int64{}
	p := NewPrinter()
	p.getNow = func() time.Time { return time.UnixMilli(nowMilli.Load()) }

	p.AtMostEvery(time.Minute).Infof("hey there %d", 1)
	p.AtMostEvery(time.Minute).Warnf("hey there %d", 2)
	p.AtMostEvery(time.Minute).Errorf("hey there %d", 3)
	nowMilli.Add(time.Minute.Milliseconds())
	p.AtMostEvery(time.Minute).Errorf("hey there %d", 4)
	p.AtMostEvery(time.Minute).Warnf("hey there %d", 5)
	p.AtMostEvery(time.Minute).Infof("hey there %d", 6)

	assert.Equal(t,
		[]PrinterMessage{
			{Info, "hey there 1"},
			{Error, "hey there 4"},
		},
		p.Read())
}
