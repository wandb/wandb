package filestream

import (
	"fmt"

	"github.com/segmentio/encoding/json"
	"google.golang.org/protobuf/reflect/protoreflect"

	"github.com/wandb/wandb/core/internal/lib/corelib"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

var boolTrue bool = true

type processedChunk struct {
	fileType   ChunkTypeEnum
	fileLine   string
	Complete   *bool
	Exitcode   *int32
	Preempting bool
	Uploaded   []string
}

func (fs *FileStream) addProcess(rec *pb.Record) {
	fs.processChan <- rec
}

func (fs *FileStream) processRecord(record *pb.Record) {
	switch x := record.RecordType.(type) {
	case *pb.Record_History:
		fs.streamHistory(x.History)
	case *pb.Record_Summary:
		fs.streamSummary(x.Summary)
	case *pb.Record_Stats:
		fs.streamSystemMetrics(x.Stats)
	case *pb.Record_OutputRaw:
		fs.streamOutputRaw(x.OutputRaw)
	case *pb.Record_Exit:
		fs.streamFinish(x.Exit)
	case *pb.Record_Preempting:
		fs.streamPreempting(x.Preempting)
	case nil:
		err := fmt.Errorf("filestream: field not set")
		fs.logger.CaptureFatalAndPanic("filestream error:", err)
	default:
		err := fmt.Errorf("filestream: Unknown type %T", x)
		fs.logger.CaptureFatalAndPanic("filestream error:", err)
	}
}

func (fs *FileStream) loopProcess(inChan <-chan protoreflect.ProtoMessage) {
	fs.logger.Debug("filestream: open", "path", fs.path)

	for message := range inChan {
		fs.logger.Debug("filestream: record", "message", message)
		switch x := message.(type) {
		case *pb.Record:
			fs.processRecord(x)
		case *pb.FilesUploaded:
			fs.streamFilesUploaded(x)
		case nil:
			err := fmt.Errorf("filestream: field not set")
			fs.logger.CaptureFatalAndPanic("filestream error:", err)
		default:
			err := fmt.Errorf("filestream: Unknown type %T", x)
			fs.logger.CaptureFatalAndPanic("filestream error:", err)
		}
	}
}

func (fs *FileStream) streamHistory(msg *pb.HistoryRecord) {
	line, err := corelib.JsonifyItems(msg.Item)
	if err != nil {
		fs.logger.CaptureFatalAndPanic("json unmarshal error", err)
	}
	fs.addTransmit(processedChunk{
		fileType: HistoryChunk,
		fileLine: line,
	})
}

func (fs *FileStream) streamSummary(msg *pb.SummaryRecord) {
	line, err := corelib.JsonifyItems(msg.Update)
	if err != nil {
		fs.logger.CaptureFatalAndPanic("json unmarshal error", err)
	}
	fs.addTransmit(processedChunk{
		fileType: SummaryChunk,
		fileLine: line,
	})
}

func (fs *FileStream) streamOutputRaw(msg *pb.OutputRawRecord) {
	fs.addTransmit(processedChunk{
		fileType: OutputChunk,
		fileLine: msg.Line,
	})
}

func (fs *FileStream) streamSystemMetrics(msg *pb.StatsRecord) {
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
		fs.logger.CaptureError("sender: sendSystemMetrics: failed to marshal system metrics", err)
		return
	}

	fs.addTransmit(processedChunk{
		fileType: EventsChunk,
		fileLine: string(line),
	})
}

func (fs *FileStream) streamPreempting(exitRecord *pb.RunPreemptingRecord) {
	fs.addTransmit(processedChunk{
		Preempting: true,
	})
}

func (fs *FileStream) streamFilesUploaded(msg *pb.FilesUploaded) {
	fs.addTransmit(processedChunk{
		Uploaded: msg.Files,
	})
}

func (fs *FileStream) streamFinish(exitRecord *pb.RunExitRecord) {
	fs.addTransmit(processedChunk{
		Complete: &boolTrue,
		Exitcode: &exitRecord.ExitCode,
	})
}
