package filetransfer

import (
	"os"
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

func TestDefaultFileTransfer_Download(t *testing.T) {
	type fields struct {
		client *retryablehttp.Client
		logger *observability.CoreLogger
	}
	type args struct {
		task *Task
	}
	logger := observability.NewNoOpLogger()
	settings := service.Settings{}

	client := clients.NewRetryClient(
		clients.WithRetryClientLogger(logger),
		clients.WithRetryClientRetryMax(int(settings.GetXFileTransferRetryMax().GetValue())),
		clients.WithRetryClientRetryWaitMin(time.Duration(settings.GetXFileTransferRetryWaitMinSeconds().GetValue()*int32(time.Second))),
		clients.WithRetryClientRetryWaitMax(time.Duration(settings.GetXFileTransferRetryWaitMaxSeconds().GetValue()*int32(time.Second))),
		clients.WithRetryClientHttpTimeout(time.Duration(settings.GetXFileTransferTimeoutSeconds().GetValue()*int32(time.Second))),
	)
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool
	}{
		{
			name: "test download file successfully",
			fields: fields{
				client: client,
				logger: observability.NewNoOpLogger(),
			},
			args: args{
				task: &Task{
					Path:     "./test-download-file.txt",
					Url:      "https://wandb.ai",
					FileType: ArtifactFile,
				},
			},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ft := &DefaultFileTransfer{
				client: tt.fields.client,
				logger: tt.fields.logger,
			}
			if err := ft.Download(tt.args.task); (err != nil) != tt.wantErr {
				t.Errorf("DefaultFileTransfer.Download() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
	// clean up test file
	_ = os.Remove("./test-download-file.txt")
}
