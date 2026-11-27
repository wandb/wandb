package filestream

import (
	"encoding/json"
	"fmt"
	"maps"
	"slices"

	"google.golang.org/protobuf/proto"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
)

const protoContentType = "application/vnd.wandb.filestream.proto+v1"

func (fs *fileStream) marshalRequest(data *FileStreamRequestJSON) ([]byte, string, error) {
	if data.TypedHistory != nil {
		if !fs.typedHistoryEnabled {
			return nil, "", fmt.Errorf("filestream: typed history was not negotiated")
		}
		if _, ok := data.Files[HistoryFileName]; ok {
			return nil, "", fmt.Errorf("filestream: request contains both typed and JSONL history")
		}
	}

	if fs.typedHistoryEnabled {
		body, err := proto.Marshal(data.toProto())
		if err != nil {
			return nil, "", fmt.Errorf("filestream: protobuf marshal error in send(): %w", err)
		}
		return body, protoContentType, nil
	}

	body, err := json.Marshal(data)
	if err != nil {
		return nil, "", fmt.Errorf("filestream: json marshal error in send(): %w", err)
	}
	return body, "application/json", nil
}

func (r *FileStreamRequestJSON) toProto() *filestreamv1.FileStreamUpload {
	upload := &filestreamv1.FileStreamUpload{
		History:    r.TypedHistory,
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
	return upload
}
