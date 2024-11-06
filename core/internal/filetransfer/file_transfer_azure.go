package filetransfer

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/Azure/azure-sdk-for-go/sdk/azidentity"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob/blob"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob/container"
	"github.com/wandb/wandb/core/internal/observability"
	"golang.org/x/sync/errgroup"
)

const maxAzureWorkers int = 500
const azureScheme string = "https"

type AzureClientsMap struct {
	// clients is a map of account URLs to azblob.Client objects
	clients sync.Map

	// once is a map of account URLs to sync.Once objects to ensure
	// that we only set up each Azure account client once
	once sync.Map
}

func NewAzureClientsMap() *AzureClientsMap {
	return &AzureClientsMap{clients: sync.Map{}, once: sync.Map{}}
}

func (am *AzureClientsMap) GetClient(accountUrl string) (*azblob.Client, error) {
	client, ok := am.clients.Load(accountUrl)
	if !ok {
		return nil, fmt.Errorf("client not found")
	}
	return client.(*azblob.Client), nil
}

// AzureFileTransfer uploads or downloads files to/from Azure
type AzureFileTransfer struct {
	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// fileTransferStats is used to track upload/download progress
	fileTransferStats FileTransferStats

	// background context is used to create a reader and get the client
	ctx context.Context

	// clients is a map of account URLs to azblob.Client objects
	clients *AzureClientsMap
}

// NewAzureFileTransfer creates a new fileTransfer.
func NewAzureFileTransfer(
	clients *AzureClientsMap,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *AzureFileTransfer {
	ctx := context.Background()
	if clients == nil {
		clients = NewAzureClientsMap()
	}
	return &AzureFileTransfer{
		logger:            logger,
		fileTransferStats: fileTransferStats,
		ctx:               ctx,
		clients:           clients,
	}
}

// SetupClient sets up the Azure account client if it is not currently set
func (ft *AzureFileTransfer) SetupClient(accountUrl string) {
	onceVal, _ := ft.clients.once.LoadOrStore(accountUrl, &sync.Once{})
	once := onceVal.(*sync.Once)
	once.Do(func() {
		cred, err := azidentity.NewDefaultAzureCredential(nil)
		if err != nil {
			ft.logger.Error("Unable to create Azure credential", "err", err)
			return
		}
		client, err := azblob.NewClient(accountUrl, cred, nil)
		if err != nil {
			ft.logger.Error("Unable to create Azure client", "err", err)
			return
		}
		ft.clients.clients.Store(accountUrl, client)
	})
}

// SetupBlobClient sets up the Azure blob client
func (ft *AzureFileTransfer) SetupBlobClient(task *ReferenceArtifactDownloadTask) (*blob.Client, error) {
	cred, err := azidentity.NewDefaultAzureCredential(nil)
	if err != nil {
		ft.logger.Error("Unable to create Azure credential", "err", err)
		return nil, err
	}
	client, err := blob.NewClient(task.Reference, cred, nil)
	if err != nil {
		ft.logger.Error("Unable to create Azure client", "err", err)
		return nil, err
	}
	versionId, ok := task.VersionIDString()
	if ok {
		client, err = client.WithVersionID(versionId)
		if err != nil {
			ft.logger.Error("Unable to set version ID", "err", err)
			return nil, err
		}
	}
	return client, nil
}

// SetupContainerClient sets up the Azure container client
func (ft *AzureFileTransfer) SetupContainerClient(containerName string) (*container.Client, error) {
	cred, err := azidentity.NewDefaultAzureCredential(nil)
	if err != nil {
		ft.logger.Error("Unable to create Azure credential", "err", err)
		return nil, err
	}
	client, err := container.NewClient(containerName, cred, nil)
	if err != nil {
		ft.logger.Error("Unable to create Azure client", "err", err)
		return nil, err
	}
	return client, nil
}

// Upload uploads a file to the server.
func (ft *AzureFileTransfer) Upload(task *ReferenceArtifactUploadTask) error {
	ft.logger.Debug("Azure file transfer: uploading file", "path", task.PathOrPrefix)

	return nil
}

type ParsedBlobInfo struct {
	AccountUrl string
	Container  string
	BlobPrefix string
}

// Download downloads a file from the server.
func (ft *AzureFileTransfer) Download(task *ReferenceArtifactDownloadTask) error {
	ft.logger.Debug("Azure file transfer: downloading file", "path", task.PathOrPrefix, "ref", task.Reference)

	// Parse the reference path to get the account URL and blob path
	accountUrl, fullBlobPath, err := parseCloudReference(task.Reference, azureScheme)
	if err != nil {
		return ft.formatDownloadError("error parsing reference", err)
	}
	pathSplit := strings.SplitN(fullBlobPath, "/", 2)
	fullAccountUrl := fmt.Sprintf("%s://%s", azureScheme, accountUrl)
	blobInfo := ParsedBlobInfo{
		AccountUrl: fullAccountUrl,
		Container:  pathSplit[0],
		BlobPrefix: pathSplit[1],
	}

	// Setup the client if it is not already set up
	ft.SetupClient(fullAccountUrl)
	_, ok := ft.clients.clients.Load(fullAccountUrl)
	if !ok {
		return ft.formatDownloadError("error setting up Azure account client", fmt.Errorf("client not found"))
	}

	var blobNames []string
	if task.HasSingleFile() {
		blobName, versionId, err := ft.getBlobName(blobInfo, task)
		if err != nil {
			return ft.formatDownloadError("error getting correctblob name and version", err)
		}
		if versionId != "" {
			task.SetVersionID(versionId)
		}
		blobNames = []string{blobName}
	} else {
		blobNames, err = ft.listBlobsWithPrefix(blobInfo)
		if err != nil {
			return ft.formatDownloadError(fmt.Sprintf("error finding blobs with prefix %s", blobInfo.BlobPrefix), err)
		}
	}

	err = ft.downloadFiles(blobInfo, blobNames, task)
	if err != nil {
		return ft.formatDownloadError(fmt.Sprintf("error downloading reference %s", task.Reference), err)
	}
	return nil
}

// getBlobName tries to get the blob name and version ID that matches the expected digest for the given task
func (ft *AzureFileTransfer) getBlobName(blobInfo ParsedBlobInfo, task *ReferenceArtifactDownloadTask) (string, string, error) {
	blobClient, err := ft.SetupBlobClient(task)
	if err != nil {
		return "", "", err
	}
	properties, err := blobClient.GetProperties(ft.ctx, nil)
	if err != nil {
		return "", "", err
	}

	// If the etag does not match the expected digest, try to find the correct blob version
	if properties.ETag != nil && strings.Trim(string(*properties.ETag), "\"") != task.Digest {
		if task.VersionId != nil {
			return "", "", fmt.Errorf(
				"digest/etag mismatch: etag %s does not match expected digest %s",
				*properties.ETag,
				task.Digest,
			)
		}
		blobName, versionId, err := ft.getCorrectBlobVersion(blobInfo, task)
		if err != nil {
			return "", "", err
		}
		return blobName, versionId, nil
	}
	return blobInfo.BlobPrefix, "", nil
}

// getCorrectBlobVersion finds the correct blob version that matches the expected digest
func (ft *AzureFileTransfer) getCorrectBlobVersion(blobInfo ParsedBlobInfo, task *ReferenceArtifactDownloadTask) (string, string, error) {
	containerClient, err := ft.SetupContainerClient(fmt.Sprintf("%s/%s", blobInfo.AccountUrl, blobInfo.Container))
	if err != nil {
		return "", "", err
	}

	pager := containerClient.NewListBlobsFlatPager(&container.ListBlobsFlatOptions{
		Prefix: &blobInfo.BlobPrefix,
		Include: container.ListBlobsInclude{
			Versions: true,
		},
	})

	for pager.More() {
		resp, err := pager.NextPage(ft.ctx)
		if err != nil {
			return "", "", err
		}

		for _, blob := range resp.Segment.BlobItems {
			blobClient, err := containerClient.NewBlobClient(*blob.Name).WithVersionID(*blob.VersionID)
			if err != nil {
				return "", "", err
			}
			properties, err := blobClient.GetProperties(ft.ctx, nil)
			if err != nil {
				return "", "", err
			}
			if properties.ETag != nil && strings.Trim(string(*properties.ETag), "\"") == task.Digest {
				return *blob.Name, *blob.VersionID, nil
			}
		}
	}
	return "", "", fmt.Errorf(
		"digest/etag mismatch: unable to find version with expected digest %s for reference %s",
		task.Digest,
		task.Reference,
	)
}

// listBlobs lists all the blobs in the container with the given prefix
func (ft *AzureFileTransfer) listBlobsWithPrefix(blobInfo ParsedBlobInfo) ([]string, error) {
	client, err := ft.clients.GetClient(blobInfo.AccountUrl)
	if err != nil {
		return nil, err
	}

	// List the blobs in the container
	pager := client.NewListBlobsFlatPager(blobInfo.Container, &azblob.ListBlobsFlatOptions{
		Prefix: &blobInfo.BlobPrefix,
	})

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

// downloadFiles downloads all of the blobs with the given names
func (ft *AzureFileTransfer) downloadFiles(
	blobInfo ParsedBlobInfo,
	blobNames []string,
	task *ReferenceArtifactDownloadTask,
) error {
	g := new(errgroup.Group)
	g.SetLimit(maxAzureWorkers)
	for _, blobName := range blobNames {
		g.Go(func() error {
			objectRelativePath, _ := strings.CutPrefix(blobName, blobInfo.BlobPrefix)
			localPath := filepath.Join(task.PathOrPrefix, filepath.FromSlash(objectRelativePath))
			return ft.downloadBlobToFile(blobInfo, blobName, task, localPath)
		})
	}

	return g.Wait()
}

// downloadBlobToFile downloads a blob to a file at the given local path
func (ft *AzureFileTransfer) downloadBlobToFile(
	blobInfo ParsedBlobInfo,
	blobName string,
	task *ReferenceArtifactDownloadTask,
	localPath string,
) error {
	// Create or open a local file where we can download the blob
	if err := os.MkdirAll(filepath.Dir(localPath), 0755); err != nil {
		return fmt.Errorf("unable to create destination directory %s: %w", filepath.Dir(localPath), err)
	}

	destination, err := os.Create(localPath)
	if err != nil {
		return fmt.Errorf("unable to create destination file %s: %w", localPath, err)
	}

	// If version ID is specified, use the blob client to download the blob
	_, ok := task.VersionIDString()
	if ok {
		blobClient, err := ft.SetupBlobClient(task)
		if err != nil {
			return err
		}
		_, err = blobClient.DownloadFile(ft.ctx, destination, nil)
		return err
	} else {
		// Download the blob to the local file
		client, err := ft.clients.GetClient(blobInfo.AccountUrl)
		if err != nil {
			return err
		}
		_, err = client.DownloadFile(ft.ctx, blobInfo.Container, blobName, destination, nil)
		return err
	}
}

func (ft *AzureFileTransfer) formatDownloadError(message string, err error) error {
	return fmt.Errorf("AzureFileTransfer: Download: %s: %w", message, err)
}
