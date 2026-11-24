package filestream

import (
	"encoding/json"
	"fmt"
	"maps"
	"slices"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
)

const protoContentType = "application/vnd.wandb.filestream.proto+v1"

func (fs *fileStream) marshalRequest(data *FileStreamRequestJSON) ([]byte, string, error) {
	if fs.useProto() {
		body, err := proto.Marshal(data.toProto())
		if err != nil {
			return nil, "", fmt.Errorf("filestream: protobuf marshal error in send(): %v", err)
		}
		return body, protoContentType, nil
	}

	body, err := json.Marshal(data)
	if err != nil {
		return nil, "", fmt.Errorf("filestream: json marshal error in send(): %v", err)
	}
	return body, "application/json", nil
}

// toProto builds the wire body without modifying records from the transaction log.
func (r *FileStreamRequestJSON) toProto() *filestreamv1.FileStreamUpload {
	upload := &filestreamv1.FileStreamUpload{
		Uploaded:   r.Uploaded,
		Preempting: r.Preempting,
		Complete:   r.Complete,
		ExitCode:   r.ExitCode,
	}
	for _, name := range slices.Sorted(maps.Keys(r.Files)) {
		chunk := r.Files[name]
		upload.Files = append(upload.Files, &filestreamv1.FileStreamChunk{
			Name: name, Offset: int64(chunk.Offset), Content: chunk.Content,
		})
	}
	if r.SystemMetrics != nil {
		chunk := proto.CloneOf(r.SystemMetrics)
		chunk.SentAt = timestamppb.Now()
		if len(chunk.Records) > 0 {
			chunk.Writer = chunk.Records[0].GetWriter()
		}
		for _, record := range chunk.Records {
			if proto.Equal(record.Writer, chunk.Writer) {
				record.Writer = nil
			}
			record.XInfo = nil
		}
		upload.SystemMetrics = chunk
	}
	return upload
}
