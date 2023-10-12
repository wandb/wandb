package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"time"

	"cloud.google.com/go/storage"
)

// streamFileUpload uploads an object via a stream.
func streamFileUpload(w io.Writer, bucket, object string) error {
	// bucket := "bucket-name"
	// object := "object-name"
	ctx := context.Background()
	client, err := storage.NewClient(ctx)
	if err != nil {
		return fmt.Errorf("storage.NewClient: %w", err)
	}
	defer client.Close()

	b := []byte("Hello world.")
	buf := bytes.NewBuffer(b)

	ctx, cancel := context.WithTimeout(ctx, time.Second*50)
	defer cancel()

	// Upload an object with storage.Writer.
	wc := client.Bucket(bucket).Object(object).NewWriter(ctx)
	wc.ChunkSize = 0 // note retries are not supported for chunk size 0.

	if _, err = io.Copy(wc, buf); err != nil {
		return fmt.Errorf("io.Copy: %w", err)
	}
	// Data can continue to be added to the file until the writer is closed.
	if err := wc.Close(); err != nil {
		return fmt.Errorf("Writer.Close: %w", err)
	}
	fmt.Fprintf(w, "%v uploaded to %v.\n", object, bucket)

	return nil
}

func main() {
	/*
		- run stuff with GOOGLE_APPLICATION_CREDENTIALS=service-acc-creds.json python ... or go run ...
		- https://cloud.google.com/storage/docs/uploading-objects-from-memory
		- https://cloud.google.com/iam/docs/keys-create-delete#iam-service-account-keys-create-console
	*/
	err := streamFileUpload(os.Stdout, "dotwandb", "loltest")
	if err != nil {
		panic(err)
	}
}
