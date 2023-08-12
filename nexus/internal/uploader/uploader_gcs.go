package uploader

/*

import (
	"context"
	"fmt"
	"io"
	"log"
	"os"

	"cloud.google.com/go/storage"
)

const (
	ChunkSize = 4 * 1024 * 1024 // 4MB chunks
	SignedURL = "your-signed-url"
)

func uploadFile(ctx context.Context, client *storage.Client, filePath string, url string) error {
	file, err := os.Open(filePath)
	if err != nil {
		return fmt.Errorf("failed to open file: %v", err)
	}
	defer file.Close()

	writer := storage.NewWriter(ctx, client, url)
	writer.ChunkSize = ChunkSize

	if _, err = io.Copy(writer, file); err != nil {
		return fmt.Errorf("failed to copy data to the writer: %v", err)
	}

	if err := writer.Close(); err != nil {
		return fmt.Errorf("failed to close writer: %v", err)
	}

	return nil
}

func main() {
	ctx := context.Background()

	// You do not need to provide any credentials when using a signed URL
	client, err := storage.NewClient(ctx)
	if err != nil {
		log.Fatalf("failed to create storage client: %v", err)
	}

	filePath := "path/to/your/file.ext"
	if err := uploadFile(ctx, client, filePath, SignedURL); err != nil {
		log.Fatalf("failed to upload file: %v", err)
	}

	log.Println("File uploaded successfully.")
}

*/
