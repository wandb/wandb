package sentry

import (
	"context"
	"sync"
	"time"
)

const (
	batchSize    = 100
	batchTimeout = 5 * time.Second
)

type BatchLogger struct {
	client    *Client
	logCh     chan Log
	cancel    context.CancelFunc
	wg        sync.WaitGroup
	startOnce sync.Once
}

func NewBatchLogger(client *Client) *BatchLogger {
	return &BatchLogger{
		client: client,
		logCh:  make(chan Log, batchSize),
	}
}

func (l *BatchLogger) Start() {
	l.startOnce.Do(func() {
		ctx, cancel := context.WithCancel(context.Background())
		l.cancel = cancel
		l.wg.Add(1)
		go l.run(ctx)
	})
}

func (l *BatchLogger) Flush() {
	if l.cancel != nil {
		l.cancel()
		l.wg.Wait()
	}
}

func (l *BatchLogger) run(ctx context.Context) {
	defer l.wg.Done()
	var logs []Log
	timer := time.NewTimer(batchTimeout)

	for {
		select {
		case log := <-l.logCh:
			logs = append(logs, log)
			if len(logs) >= batchSize {
				l.processEvent(logs)
				logs = nil
				if !timer.Stop() {
					<-timer.C
				}
				timer.Reset(batchTimeout)
			}
		case <-timer.C:
			if len(logs) > 0 {
				l.processEvent(logs)
				logs = nil
			}
			timer.Reset(batchTimeout)
		case <-ctx.Done():
			// Drain remaining logs from channel
		drain:
			for {
				select {
				case log := <-l.logCh:
					logs = append(logs, log)
				default:
					break drain
				}
			}

			if len(logs) > 0 {
				l.processEvent(logs)
			}
			return
		}
	}
}

func (l *BatchLogger) processEvent(logs []Log) {
	event := NewEvent()
	event.Timestamp = time.Now()
	event.Type = logEvent.Type
	event.Logs = logs
	l.client.CaptureEvent(event, nil, nil)
}
