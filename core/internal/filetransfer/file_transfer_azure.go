package filetransfer

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/Azure/azure-sdk-for-go/sdk/azidentity"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob/blob"
	"github.com/wandb/wandb/core/internal/observability"
	"golang.org/x/sync/errgroup"
)

const maxAzureWorkers int = 500
const azureScheme string = "https"

// AzureFileTransfer uploads or downloads files to/from Azure
type AzureFileTransfer struct {
	// client is the HTTP client for the file transfer
	client *azblob.Client

	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// fileTransferStats is used to track upload/download progress
	fileTransferStats FileTransferStats

	// background context is used to create a reader and get the client
	ctx context.Context

	blobClient *blob.Client
}

// NewAzureFileTransfer creates a new fileTransfer.
func NewAzureFileTransfer(
	client *azblob.Client,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *AzureFileTransfer {
	ctx := context.Background()
	return &AzureFileTransfer{
		logger:            logger,
		client:            client,
		fileTransferStats: fileTransferStats,
		ctx:               ctx,
	}
}

// SetupClient sets up the Azure client if it is not currently set
func (ft *AzureFileTransfer) SetupClient(accountUrl string) error {
	cred, err := azidentity.NewDefaultAzureCredential(nil)
	if err != nil {
		ft.logger.Error("Unable to create Azure credential", "err", err)
		return err
	}
	client, err := azblob.NewClient(accountUrl, cred, nil)
	if err != nil {
		ft.logger.Error("Unable to create Azure client", "err", err)
		return err
	}
	ft.client = client
	return nil
}

// SetupClient sets up the Azure client if it is not currently set
func (ft *AzureFileTransfer) SetupBlobClient(blobUrl string, versionId string) error {
	cred, err := azidentity.NewDefaultAzureCredential(nil)
	if err != nil {
		ft.logger.Error("Unable to create Azure credential", "err", err)
		return err
	}
	client, err := blob.NewClient(blobUrl, cred, nil)
	if err != nil {
		ft.logger.Error("Unable to create Azure client", "err", err)
		return err
	}
	client, err = client.WithVersionID(versionId)
	if err != nil {
		ft.logger.Error("Unable to set version ID", "err", err)
		return err
	}
	ft.blobClient = client
	return nil
}

// Upload uploads a file to the server.
func (ft *AzureFileTransfer) Upload(task *ReferenceArtifactUploadTask) error {
	ft.logger.Debug("Azure file transfer: uploading file", "path", task.PathOrPrefix)

	return nil
}

// Upload uploads a file to the server.
func (ft *AzureFileTransfer) Download(task *ReferenceArtifactDownloadTask) error {
	ft.logger.Debug("Azure file transfer: downloading file", "path", task.PathOrPrefix)

	// Parse the reference path to get the scheme, bucket, and object
	accountUrl, fullBlobPath, err := parseCloudReference(task.Reference, azureScheme)
	if err != nil {
		return ft.formatDownloadError("error parsing reference", err)
	}
	pathSplit := strings.SplitN(fullBlobPath, "/", 2)
	container := pathSplit[0]
	blobName := pathSplit[1]

	fullAccountUrl := fmt.Sprintf("%s://%s", azureScheme, accountUrl)
	err = ft.SetupClient(fullAccountUrl)
	if err != nil {
		return ft.formatDownloadError("error setting up Azure client", err)
	}

	if task.HasSingleFile() {
		err := ft.downloadBlobToFile(container, blobName, task, nil)
		if err != nil {
			return ft.formatDownloadError("error downloading blob", err)
		}
	} else {
		ft.logger.Debug("Azure file transfer: downloading multiple files", "path", task.PathOrPrefix)
		blobNames, err := ft.listBlobsFlat(container)
		if err != nil {
			return ft.formatDownloadError("error listing blobs", err)
		}
		err = ft.downloadFiles(container, fullBlobPath, blobNames, task)
		if err != nil {
			return ft.formatDownloadError("error downloading objects", err)
		}
	}

	return nil
}

func (ft *AzureFileTransfer) downloadFiles(
	containerName string,
	fullBlobPath string,
	blobNames []string,
	task *ReferenceArtifactDownloadTask,
) error {
	g := new(errgroup.Group)
	g.SetLimit(maxAzureWorkers)
	for _, blobName := range blobNames {
		g.Go(func() error {
			objectRelativePath, _ := strings.CutPrefix(blobName, fullBlobPath)
			localPath := filepath.Join(task.PathOrPrefix, filepath.FromSlash(objectRelativePath))
			return ft.downloadBlobToFile(containerName, blobName, task, &localPath)
		})
	}

	return g.Wait()
}

func (ft *AzureFileTransfer) downloadBlobToFile(
	containerName string,
	blobName string,
	task *ReferenceArtifactDownloadTask,
	overridePath *string,
) error {
	downloadPath := task.PathOrPrefix
	if overridePath != nil {
		downloadPath = *overridePath
	}

	// Create or open a local file where we can download the blob
	if err := os.MkdirAll(filepath.Dir(downloadPath), 0755); err != nil {
		return fmt.Errorf("unable to create destination directory %s: %w", filepath.Dir(downloadPath), err)
	}

	destination, err := os.Create(downloadPath)
	if err != nil {
		return fmt.Errorf("unable to create destination file %s: %w", downloadPath, err)
	}

	// If version ID is specified, append it to the blob name
	versionId, ok := task.VersionIDString()
	if ok {
		err = ft.SetupBlobClient(task.Reference, versionId)
		if err != nil {
			return ft.formatDownloadError("error setting up Azure blob client", err)
		}
		_, err = ft.blobClient.DownloadFile(ft.ctx, destination, nil)
		return err
	} else {
		// Download the blob to the local file
		_, err = ft.client.DownloadFile(ft.ctx, containerName, blobName, destination, nil)
		return err
	}
}

func (ft *AzureFileTransfer) listBlobsFlat(containerName string) ([]string, error) {
	// List the blobs in the container
	pager := ft.client.NewListBlobsFlatPager(containerName, nil)

	blobNames := []string{}
	for pager.More() {
		resp, err := pager.NextPage(ft.ctx)
		if err != nil {
			return nil, err
		}

		for _, blob := range resp.Segment.BlobItems {
			blobNames = append(blobNames, *blob.Name)
		}
	}

	return blobNames, nil
}

func (ft *AzureFileTransfer) formatDownloadError(message string, err error) error {
	return fmt.Errorf("AzureFileTransfer: Download: %s: %w", message, err)
}
