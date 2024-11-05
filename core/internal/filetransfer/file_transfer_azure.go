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

// SetupClient sets up the Azure client if it is not currently set
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

// SetupClient sets up the Azure client if it is not currently set
func (ft *AzureFileTransfer) SetupBlobClient(blobUrl string, versionId string) (*blob.Client, error) {
	cred, err := azidentity.NewDefaultAzureCredential(nil)
	if err != nil {
		ft.logger.Error("Unable to create Azure credential", "err", err)
		return nil, err
	}
	client, err := blob.NewClient(blobUrl, cred, nil)
	if err != nil {
		ft.logger.Error("Unable to create Azure client", "err", err)
		return nil, err
	}
	client, err = client.WithVersionID(versionId)
	if err != nil {
		ft.logger.Error("Unable to set version ID", "err", err)
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

// Upload uploads a file to the server.
func (ft *AzureFileTransfer) Download(task *ReferenceArtifactDownloadTask) error {
	ft.logger.Debug("Azure file transfer: downloading file", "path", task.PathOrPrefix, "ref", task.Reference)

	// Parse the reference path to get the scheme, bucket, and object
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
		return ft.formatDownloadError("error setting up Azure client", fmt.Errorf("client not found"))
	}

	var blobNames []string
	if task.HasSingleFile() {
		blobNames = []string{blobInfo.BlobPrefix}
	} else {
		blobNames, err = ft.listBlobsWithPrefix(blobInfo)
		if err != nil {
			return ft.formatDownloadError("error listing blobs", err)
		}
	}

	err = ft.downloadFiles(blobInfo, blobNames, task)
	if err != nil {
		return ft.formatDownloadError(fmt.Sprintf("error downloading reference %s", task.Reference), err)
	}
	return nil
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
	versionId, ok := task.VersionIDString()
	if ok {
		blobClient, err := ft.SetupBlobClient(task.Reference, versionId)
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
