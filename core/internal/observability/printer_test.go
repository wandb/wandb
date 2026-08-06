package observability

import (
	"sync/atomic"
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestReadAfterWrite(t *testing.T) {
	p := NewPrinter(10)
	defer p.Close()

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
	p := NewPrinter(10)
	defer p.Close()
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

func TestDiscardedMessageWarning(t *testing.T) {
	p := NewPrinter(1)
	defer p.Close()

	p.Infof("message 1")
	p.Infof("message 2")

	assert.Equal(t,
		[]PrinterMessage{
			{Info, "message 1"},
			{Warning, "Some messages exceeded the buffer and were not printed."},
		},
		p.Read())
}

func TestReadWait_BlocksUntilMessage(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		p := NewPrinter(1)
		defer p.Close()

		var receivedMessage string
		go func() {
			messages := p.ReadWait(t.Context())
			receivedMessage = messages[0].Content
		}()

		// Wait for the ReadWait to block.
		synctest.Wait()

		// Unblock it, wait for it to receive the message.
		p.Infof("message")
		synctest.Wait()

		assert.Equal(t, "message", receivedMessage)
	})
}

func TestReadWait_UnblocksOnClose(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		p := NewPrinter(1)

		var receivedMessages []PrinterMessage
		go func() {
			receivedMessages = p.ReadWait(t.Context())
		}()

		// Wait for the ReadWait to block.
		synctest.Wait()

		// Unblock by closing.
		p.Close()
		synctest.Wait()

		assert.Empty(t, receivedMessages)
	})
}
