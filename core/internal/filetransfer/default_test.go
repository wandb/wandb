package filetransfer_test

import (
	"os"
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/retryableclient"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

func TestDefaultFileTransfer_Download(t *testing.T) {
	type fields struct {
		client *retryablehttp.Client
		logger *observability.CoreLogger
	}
	type args struct {
		task *filetransfer.Task
	}
	logger := observability.NewNoOpLogger()
	settings := pb.Settings{}

	client := retryableclient.NewRetryClient(
		retryableclient.WithRetryClientLogger(logger),
		retryableclient.WithRetryClientRetryMax(int(settings.GetXFileTransferRetryMax().GetValue())),
		retryableclient.WithRetryClientRetryWaitMin(time.Duration(settings.GetXFileTransferRetryWaitMinSeconds().GetValue()*int32(time.Second))),
		retryableclient.WithRetryClientRetryWaitMax(time.Duration(settings.GetXFileTransferRetryWaitMaxSeconds().GetValue()*int32(time.Second))),
		retryableclient.WithRetryClientHttpTimeout(time.Duration(settings.GetXFileTransferTimeoutSeconds().GetValue()*int32(time.Second))),
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
				task: &filetransfer.Task{
					Path: "./test-download-file.txt",
					Url:  "https://wandb.ai",
				},
			},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ft := &filetransfer.DefaultTransferer{
				Client: tt.fields.client,
				Logger: tt.fields.logger,
			}
			if err := ft.Download(tt.args.task); (err != nil) != tt.wantErr {
				t.Errorf("DefaultFileTransfer.Download() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
	// clean up test file
	_ = os.Remove("./test-download-file.txt")
}
