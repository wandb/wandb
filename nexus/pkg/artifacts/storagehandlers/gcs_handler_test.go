package storagehandlers

import (
	"context"
	"testing"

	"cloud.google.com/go/storage"
	"github.com/stretchr/testify/mock"
	"github.com/wandb/wandb/nexus/pkg/artifacts"
	"github.com/wandb/wandb/nexus/pkg/observability"
)

type mockGCSClient struct {
	mock.Mock
	BucketHandle *BucketHandle
	CloseError   error
}

func (m *mockGCSClient) Bucket(name string) *storage.BucketHandle {
	return &storage.BucketHandle{}
}

func (m *mockGCSClient) Close() error {
	return m.CloseError
}

type BucketHandle struct {
	ObjectHandle *mockObjectHandle
}

func (m *BucketHandle) Object(string) *mockObjectHandle {
	return m.ObjectHandle
}

type mockObjectHandle struct {
	ObjectHandle *storage.ObjectHandle
}

// func (o *mockObjectHandle) NewReader(ctx context.Context) (*storage.Reader, error) {
// 	return &storage.Reader{}, nil
// }

// func (o *mockObjectHandle) Attrs(ctx context.Context) (*storage.ObjectAttrs, error) {
// 	return &storage.ObjectAttrs{
// 		MD5: []byte("your-expected-md5-digest"),
// 	}, nil
// }

// mock buckethandle, objecthandle, and object.Attrs
func TestGCSStorageHandler_loadPath(t *testing.T) {
	type fields struct {
		storageHandler storageHandler
		Client         *mockGCSClient
	}

	testRef := "gs://my-ref-bucket/my-ref-obj"
	testLocal := false
	// testInvalidETag := "/1234567890abcdf/"
	// testValidETag := "/1234567890abcd/"
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
				Client: &mockGCSClient{}},
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
				Client: &mockGCSClient{}},
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
				Client: &mockGCSClient{}},
			want:    "",
			wantErr: false,
		},
		// {
		// 	name: "Returns error if manifest entry digest doesn't match etag",
		// 	fields: fields{
		// 		storageHandler: storageHandler{
		// 			Ctx:    context.TODO(),
		// 			Logger: observability.NewNoOpLogger(),
		// 			ManifestEntry: artifacts.ManifestEntry{
		// 				Digest: "1234567890abcde",
		// 				Ref:    &testRef,
		// 				Size:   10,
		// 				Extra: map[string]interface{}{
		// 					"versionId": "23",
		// 				},
		// 			},
		// 		},
		// 		Client: &mockS3Client{
		// 			GetObjectOutput: &s3.GetObjectOutput{
		// 				ETag: &testInvalidETag,
		// 			},
		// 		}},
		// 	want:    "",
		// 	wantErr: true,
		// },
		// {
		// 	name: "Returns error if none of the object versions have a matching etag",
		// 	fields: fields{
		// 		storageHandler: storageHandler{
		// 			Ctx:    context.TODO(),
		// 			Logger: observability.NewNoOpLogger(),
		// 			ManifestEntry: artifacts.ManifestEntry{
		// 				Digest: "1234567890abcde",
		// 				Ref:    &testRef,
		// 				Size:   10,
		// 				Extra: map[string]interface{}{
		// 					"etag": "1234567890abcde",
		// 				},
		// 			},
		// 		},
		// 		Client: &mockS3Client{
		// 			GetObjectOutput: &s3.GetObjectOutput{
		// 				ETag: &testInvalidETag,
		// 			},
		// 			ListObjectVersionsOutput: &s3.ListObjectVersionsOutput{
		// 				Versions: []*s3.ObjectVersion{
		// 					{
		// 						ETag: &testInvalidETag,
		// 					},
		// 				},
		// 			},
		// 		}},
		// 	want:    "",
		// 	wantErr: true,
		// },
		// {
		// 	name: "Matches manifest entry etag with any of the version etags if digest doesn't match",
		// 	fields: fields{
		// 		storageHandler: storageHandler{
		// 			Ctx:    context.TODO(),
		// 			Logger: observability.NewNoOpLogger(),
		// 			ManifestEntry: artifacts.ManifestEntry{
		// 				Digest: "1234567890abcde",
		// 				Ref:    &testRef,
		// 				Size:   10,
		// 				Extra: map[string]interface{}{
		// 					"etag": "1234567890abcd",
		// 				},
		// 			},
		// 		},
		// 		Client: &mockS3Client{
		// 			GetObjectOutput: &s3.GetObjectOutput{
		// 				ETag: &testInvalidETag,
		// 			},
		// 			ListObjectVersionsOutput: &s3.ListObjectVersionsOutput{
		// 				Versions: []*s3.ObjectVersion{
		// 					{
		// 						ETag: &testValidETag,
		// 					},
		// 				},
		// 			},s
		// 		}},
		// 	want:    "",
		// 	wantErr: false,
		// },
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sh := GCSStorageHandler{
				storageHandler: tt.fields.storageHandler,
				Client:         tt.fields.Client,
			}
			got, err := sh.loadPath()
			if (err != nil) != tt.wantErr {
				t.Errorf("GCSStorageHandler.loadPath() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("GCSStorageHandler.loadPath() = %v, want %v", got, tt.want)
			}
		})
	}
}
