package filetransfer

// func TestDefaultFileTransfer_Download(t *testing.T) {
// 	type fields struct {
// 		client *retryablehttp.Client
// 		logger *observability.CoreLogger
// 	}
// 	type args struct {
// 		task *Task
// 	}
// 	logger := observability.NewNoOpLogger()
// 	settings := service.Settings{}

// 	client := clients.NewRetryClient(
// 		clients.WithRetryClientLogger(logger),
// 		clients.WithRetryClientRetryMax(int(settings.GetXFileTransferRetryMax().GetValue())),
// 		clients.WithRetryClientRetryWaitMin(clients.SecondsToDuration(settings.GetXFileTransferRetryWaitMinSeconds().GetValue())),
// 		clients.WithRetryClientRetryWaitMax(clients.SecondsToDuration(settings.GetXFileTransferRetryWaitMaxSeconds().GetValue())),
// 		clients.WithRetryClientHttpTimeout(clients.SecondsToDuration(settings.GetXFileTransferTimeoutSeconds().GetValue())),
// 	)
// 	tests := []struct {
// 		name    string
// 		fields  fields
// 		args    args
// 		wantErr bool
// 	}{
// 		{
// 			name: "test download file successfully",
// 			fields: fields{
// 				client: client,
// 				logger: observability.NewNoOpLogger(),
// 			},
// 			args: args{
// 				task: &Task{
// 					Path: "./test-download-file.txt",
// 					Url:  "https://wandb.ai",
// 				},
// 			},
// 			wantErr: true,
// 		},
// 	}
// 	for _, tt := range tests {
// 		t.Run(tt.name, func(t *testing.T) {
// 			ft := &DefaultFileTransfer{
// 				client: tt.fields.client,
// 				logger: tt.fields.logger,
// 			}
// 			fmt.Println("Downloading file to", tt.args.task.Path)
// 			err := ft.Download(tt.args.task)
// 			fmt.Println("Downloaded file to", err)
// 			if (err != nil) != tt.wantErr {
// 				t.Errorf("DefaultFileTransfer.Download() error = %v, wantErr %v", err, tt.wantErr)
// 			}
// 		})
// 	}
// 	// clean up test file
// 	_ = os.Remove("./test-download-file.txt")
// }
