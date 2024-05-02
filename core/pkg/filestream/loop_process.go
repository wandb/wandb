package filestream

import (
	"fmt"

	"github.com/segmentio/encoding/json"

	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/pkg/service"
)

var boolTrue = true

type processedChunk struct {
	fileType   ChunkTypeEnum
	fileLine   string
	Complete   *bool
	Exitcode   *int32
	Preempting bool
	Uploaded   []string
}

func (fs *fileStream) addProcess(input *Update) {
	select {
	case fs.processChan <- input:

	// If the filestream dies, this prevents us from blocking forever.
	case <-fs.deadChan:
	}
}

func (fs *fileStream) loopProcess(inChan <-chan *Update) {
	fs.logger.Debug("filestream: open", "path", fs.path)

	for input := range inChan {
		var err error

		switch {
		case input.HistoryRecord != nil:
			err = fs.streamHistory(input.HistoryRecord)
		case input.SummaryRecord != nil:
			err = fs.streamSummary(input.SummaryRecord)
		case input.StatsRecord != nil:
			err = fs.streamSystemMetrics(input.StatsRecord)
		case input.LogsRecord != nil:
			err = fs.streamOutputRaw(input.LogsRecord)
		case input.ExitRecord != nil:
			err = fs.streamFinish(input.ExitRecord)
		case input.PreemptRecord != nil:
			err = fs.streamPreempting()
		case input.UploadedFile != "":
			err = fs.streamFilesUploaded(input.UploadedFile)
		default:
			fs.logFatalAndStopWorking(fmt.Errorf("filestream: empty fileStreamInput"))
			return
		}

		if err != nil {
			fs.logFatalAndStopWorking(err)
			return
		}
	}
}

func (fs *fileStream) streamHistory(msg *service.HistoryRecord) error {
	if msg == nil {
		return fmt.Errorf("filestream: history record is nil")
	}

	// when logging to the same run with multiple writers, we need to
	// add a client id to the history record
	if fs.clientId != "" {
		msg.Item = append(msg.Item, &service.HistoryItem{
			Key:       "_client_id",
			ValueJson: fmt.Sprintf(`"%s"`, fs.clientId),
		})
	}

	rh := runhistory.New()
	rh.ApplyChangeRecord(
		msg.GetItem(),
		func(err error) {
			// TODO: maybe we should shut down filestream if this fails?
			fs.logger.CaptureError(
				"filestream: failed to apply history record", err)
		},
	)
	line, err := rh.Serialize()
	if err != nil {
		return fmt.Errorf("filestream: failed to serialize history: %v", err)
	}

	fs.addTransmit(processedChunk{
		fileType: HistoryChunk,
		fileLine: string(line),
	})

	return nil
}

func (fs *fileStream) streamSummary(msg *service.SummaryRecord) error {
	if msg == nil {
		return fmt.Errorf("filestream: summary record is nil")
	}

	rs := runsummary.New()
	rs.ApplyChangeRecord(
		msg,
		func(err error) {
			// TODO: maybe we should shut down filestream if this fails?
			fs.logger.CaptureError(
				"filestream: failed to apply summary record", err)
		},
	)

	line, err := rs.Serialize()
	if err != nil {
		return fmt.Errorf(
			"filestream: json unmarshal error in streamSummary: %v",
			err,
		)
	}

	fs.addTransmit(processedChunk{
		fileType: SummaryChunk,
		fileLine: string(line),
	})

	return nil
}

func (fs *fileStream) streamOutputRaw(msg *service.OutputRawRecord) error {
	fs.addTransmit(processedChunk{
		fileType: OutputChunk,
		fileLine: msg.Line,
	})

	return nil
}

func (fs *fileStream) streamSystemMetrics(msg *service.StatsRecord) error {
	// todo: there is a lot of unnecessary overhead here,
	//  we should prepare all the data in the system monitor
	//  and then send it in one record
	row := make(map[string]interface{})
	row["_wandb"] = true
	timestamp := float64(msg.GetTimestamp().Seconds) + float64(msg.GetTimestamp().Nanos)/1e9
	row["_timestamp"] = timestamp
	row["_runtime"] = timestamp - fs.settings.XStartTime.GetValue()

	for _, item := range msg.Item {
		var val interface{}
		if err := json.Unmarshal([]byte(item.ValueJson), &val); err != nil {
			e := fmt.Errorf("json unmarshal error: %v, items: %v", err, item)
			errMsg := fmt.Sprintf("sender: sendSystemMetrics: failed to marshal value: %s for key: %s", item.ValueJson, item.Key)
			fs.logger.CaptureError(errMsg, e)
			continue
		}

		row["system."+item.Key] = val
	}

	// marshal the row
	line, err := json.Marshal(row)
	if err != nil {
		// This is a non-blocking failure, so we don't return an error.
		fs.logger.CaptureError("sender: sendSystemMetrics: failed to marshal system metrics", err)
	} else {
		fs.addTransmit(processedChunk{
			fileType: EventsChunk,
			fileLine: string(line),
		})
	}

	return nil
}

func (fs *fileStream) streamFilesUploaded(path string) error {
	fs.addTransmit(processedChunk{
		Uploaded: []string{path},
	})

	return nil
}

func (fs *fileStream) streamPreempting() error {
	fs.addTransmit(processedChunk{
		Preempting: true,
	})

	return nil
}

func (fs *fileStream) streamFinish(exitRecord *service.RunExitRecord) error {
	fs.addTransmit(processedChunk{
		Complete: &boolTrue,
		Exitcode: &exitRecord.ExitCode,
	})

	return nil
}
