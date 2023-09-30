package storagehandlers

import (
	"context"
	"testing"

	"github.com/aws/aws-sdk-go/aws/awserr"
	"github.com/aws/aws-sdk-go/service/s3"
	"github.com/aws/aws-sdk-go/service/s3/s3iface"
	"github.com/wandb/wandb/nexus/pkg/artifacts"
	"github.com/wandb/wandb/nexus/pkg/observability"
)

type mockS3Client struct {
	s3iface.S3API
	GetObjectOutput          *s3.GetObjectOutput
	ListObjectVersionsOutput *s3.ListObjectVersionsOutput
	GetObjectError           error
	ListObjectVersionsError  error
}

func (m *mockS3Client) GetObject(*s3.GetObjectInput) (*s3.GetObjectOutput, error) {
	return m.GetObjectOutput, m.GetObjectError
}

func (m *mockS3Client) ListObjectVersions(*s3.ListObjectVersionsInput) (*s3.ListObjectVersionsOutput, error) {
	return m.ListObjectVersionsOutput, m.ListObjectVersionsError
}

func TestS3StorageHandler_loadPath(t *testing.T) {
	type fields struct {
		storageHandler storageHandler
		Client         s3iface.S3API
	}
	testRef := "my-ref"
	testLocal := false
	testInvalidETag := "/1234567890abcdf/"
	testValidETag := "/1234567890abcd/"
	tests := []struct {
		name    string
		fields  fields
		want    string
		wantErr bool
	}{
		{
			name: "Returns error if manifest entry reference is nil",
			fields: fields{
				storageHandler: storageHandler{
					Ctx:    context.TODO(),
					Logger: observability.NewNoOpLogger(),
					ManifestEntry: artifacts.ManifestEntry{
						Digest: "1234567890abcde",
						Size:   10,
						Extra:  make(map[string]interface{}),
					},
				},
				Client: nil},
			want:    "",
			wantErr: true,
		},
		{
			name: "Returns manifest entry reference if local is false",
			fields: fields{
				storageHandler: storageHandler{
					Ctx:    context.TODO(),
					Logger: observability.NewNoOpLogger(),
					ManifestEntry: artifacts.ManifestEntry{
						Digest: "1234567890abcde",
						Ref:    &testRef,
						Size:   10,
						Extra:  make(map[string]interface{}),
					},
					Local: &testLocal,
				},
				Client: nil},
			want:    testRef,
			wantErr: false,
		},
		{
			name: "Returns error if reference path doesn't exist",
			fields: fields{
				storageHandler: storageHandler{
					Ctx:    context.TODO(),
					Logger: observability.NewNoOpLogger(),
					ManifestEntry: artifacts.ManifestEntry{
						Digest: "1234567890abcde",
						Ref:    &testRef,
						Size:   10,
						Extra:  make(map[string]interface{}),
					},
				},
				Client: &mockS3Client{
					GetObjectError: awserr.New("NoSuchBucket", "bucket not found", nil),
				}},
			want:    "",
			wantErr: true,
		},
		{
			name: "Returns error if manifest entry digest doesn't match etag",
			fields: fields{
				storageHandler: storageHandler{
					Ctx:    context.TODO(),
					Logger: observability.NewNoOpLogger(),
					ManifestEntry: artifacts.ManifestEntry{
						Digest: "1234567890abcde",
						Ref:    &testRef,
						Size:   10,
						Extra: map[string]interface{}{
							"versionId": "23",
						},
					},
				},
				Client: &mockS3Client{
					GetObjectOutput: &s3.GetObjectOutput{
						ETag: &testInvalidETag,
					},
				}},
			want:    "",
			wantErr: true,
		},
		{
			name: "Returns error if none of the object versions have a matching etag",
			fields: fields{
				storageHandler: storageHandler{
					Ctx:    context.TODO(),
					Logger: observability.NewNoOpLogger(),
					ManifestEntry: artifacts.ManifestEntry{
						Digest: "1234567890abcde",
						Ref:    &testRef,
						Size:   10,
						Extra: map[string]interface{}{
							"etag": "1234567890abcde",
						},
					},
				},
				Client: &mockS3Client{
					GetObjectOutput: &s3.GetObjectOutput{
						ETag: &testInvalidETag,
					},
					ListObjectVersionsOutput: &s3.ListObjectVersionsOutput{
						Versions: []*s3.ObjectVersion{
							{
								ETag: &testInvalidETag,
							},
						},
					},
				}},
			want:    "",
			wantErr: true,
		},
		{
			name: "Matches manifest entry etag with any of the version etags if digest doesn't match",
			fields: fields{
				storageHandler: storageHandler{
					Ctx:    context.TODO(),
					Logger: observability.NewNoOpLogger(),
					ManifestEntry: artifacts.ManifestEntry{
						Digest: "1234567890abcde",
						Ref:    &testRef,
						Size:   10,
						Extra: map[string]interface{}{
							"etag": "1234567890abcd",
						},
					},
				},
				Client: &mockS3Client{
					GetObjectOutput: &s3.GetObjectOutput{
						ETag: &testInvalidETag,
					},
					ListObjectVersionsOutput: &s3.ListObjectVersionsOutput{
						Versions: []*s3.ObjectVersion{
							{
								ETag: &testValidETag,
							},
						},
					},
				}},
			want:    "",
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sh := &S3StorageHandler{
				storageHandler: tt.fields.storageHandler,
				Client:         tt.fields.Client,
			}
			got, err := sh.loadPath()
			if (err != nil) != tt.wantErr {
				t.Errorf("S3StorageHandler.loadPath() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("S3StorageHandler.loadPath() = %v, want %v", got, tt.want)
			}
		})
	}
}
