package ec2

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/MakeNowJust/heredoc/v2"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/ec2"
	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/internal/cliutil"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

type ConnectionMethod struct {
	Type       string `json:"type"`
	Region     string `json:"region"`
	InstanceID string `json:"instanceId"`
	AccountID  string `json:"accountId"`
}

type EC2Instance struct {
	ID               string           `json:"id"`
	Name             string           `json:"name"`
	ConnectionMethod ConnectionMethod `json:"connectionMethod"`
}

func (t *EC2Instance) Struct() map[string]interface{} {
	b, _ := json.Marshal(t)
	var m map[string]interface{}
	json.Unmarshal(b, &m)
	return m
}

func NewSyncEC2Cmd() *cobra.Command {
	var region string
	var name string
	cmd := &cobra.Command{
		Use:   "ec2",
		Short: "Sync AWS EC2 instances into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure AWS credentials are configured via environment variables or ~/.aws/credentials
			
			# Sync all EC2 instances from a region
			$ ctrlc sync aws ec2 --region us-west-2
		`),
		PreRunE: func(cmd *cobra.Command, args []string) error {
			if region == "" {
				return fmt.Errorf("region is required")
			}
			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			log.Info("Syncing EC2 instances into Ctrlplane", "config-region", region)

			ctx := context.Background()
			cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(region))
			if err != nil {
				return fmt.Errorf("failed to load AWS config: %w", err)
			}

			credentials, err := cfg.Credentials.Retrieve(ctx)
			if err != nil {
				return fmt.Errorf("failed to retrieve AWS credentials: %w", err)
			}

			log.Info("AWS credentials loaded successfully",
				"provider", credentials.Source,
				"region", region,
				"access_key_id", credentials.AccessKeyID[:4]+"****",
				"expiration", credentials.Expires,
				"type", credentials.Source,
				"profile", os.Getenv("AWS_PROFILE"),
			)

			// Create EC2 client with retry options
			ec2Client := ec2.NewFromConfig(cfg, func(o *ec2.Options) {
				o.RetryMaxAttempts = 3
				o.RetryMode = aws.RetryModeStandard
			})

			apiURL := viper.GetString("url")
			apiKey := viper.GetString("api-key")
			workspaceId := viper.GetString("workspace")

			// Get EC2 instances
			result, err := ec2Client.DescribeInstances(ctx, &ec2.DescribeInstancesInput{})
			if err != nil {
				return fmt.Errorf("failed to describe instances: %w", err)
			}

			resources := []api.AgentResource{}
			for _, reservation := range result.Reservations {
				accountId := *reservation.OwnerId
				for _, instance := range reservation.Instances {
					tags := make(map[string]string)

					for _, tag := range instance.Tags {
						tags[*tag.Key] = *tag.Value
					}

					// Get instance name from tags
					name := tags["Name"]
					if name == "" {
						name = *instance.InstanceId
					}

					// Get EC2 region from instance availability zone
					region := ""
					if instance.Placement != nil && instance.Placement.AvailabilityZone != nil {
						// Region is AZ without the last character
						region = (*instance.Placement.AvailabilityZone)[:len(*instance.Placement.AvailabilityZone)-1]
					}

					instanceData := EC2Instance{
						ID:   *instance.InstanceId,
						Name: name,
						ConnectionMethod: ConnectionMethod{
							Type:       "aws",
							Region:     region,
							InstanceID: *instance.InstanceId,
							AccountID:  accountId,
						},
					}

					// Add AWS Console URL for the instance
					consoleUrl := fmt.Sprintf("https://%s.console.aws.amazon.com/ec2/home?region=%s#InstanceDetails:instanceId=%s",
						region,
						region,
						*instance.InstanceId)

					metadata := make(map[string]string)
					for _, tag := range instance.Tags {
						if tag.Key != nil && tag.Value != nil {
							metadata[*tag.Key] = *tag.Value
							metadata["compute/tag/"+*tag.Key] = *tag.Value
							metadata["aws/tag/"+*tag.Key] = *tag.Value
						}
					}

					metadata["compute/machine-type"] = string(instance.InstanceType)
					metadata["compute/region"] = region
					metadata["compute/type"] = "standard"
					metadata["compute/architecture"] = strings.ReplaceAll(string(instance.Architecture), "_mac", "")
					metadata["compute/boot-mode"] = string(instance.BootMode)

					if instance.PlatformDetails != nil {
						metadata["compute/platform"] = *instance.PlatformDetails
					}

					if instance.CpuOptions != nil && instance.CpuOptions.CoreCount != nil {
						metadata["compute/cpu-cores"] = strconv.Itoa(int(*instance.CpuOptions.CoreCount))
						if instance.CpuOptions.ThreadsPerCore != nil {
							metadata["compute/cpu-threads-per-core"] = strconv.Itoa(int(*instance.CpuOptions.ThreadsPerCore))
							metadata["compute/cpu-threads"] = strconv.Itoa(int(*instance.CpuOptions.ThreadsPerCore) * int(*instance.CpuOptions.CoreCount))
						}
					}
					metadata["compute/hypervisor"] = string(instance.Hypervisor)

					if instance.State != nil {
						metadata["compute/state"] = string(instance.State.Name)
					}

					if instance.LaunchTime != nil {
						metadata["compute/launch-time"] = instance.LaunchTime.Format(time.RFC3339)
					}

					if instance.PrivateIpAddress != nil {
						metadata["network/private-ip"] = *instance.PrivateIpAddress
					}

					if instance.PublicIpAddress != nil {
						metadata["network/public-ip"] = *instance.PublicIpAddress
					}

					if instance.PrivateDnsName != nil {
						metadata["network/private-dns"] = *instance.PrivateDnsName
					}

					if instance.PublicDnsName != nil {
						metadata["network/public-dns"] = *instance.PublicDnsName
					}

					metadata["aws/account-id"] = accountId
					metadata["aws/region"] = region

					if instance.VpcId != nil {
						metadata["aws/vpc-id"] = *instance.VpcId
						metadata["network/id"] = *instance.VpcId
					}
					if instance.PlatformDetails != nil {
						metadata["aws/platform-details"] = string(*instance.PlatformDetails)
					}
					if instance.InstanceId != nil {
						metadata["aws/instance-id"] = *instance.InstanceId
					}

					if instance.ImageId != nil {
						metadata["aws/ami-id"] = *instance.ImageId
					}
					if instance.AmiLaunchIndex != nil {
						metadata["aws/ami-launch-index"] = strconv.Itoa(int(*instance.AmiLaunchIndex))
					}

					if instance.KeyName != nil {
						metadata["aws/key-name"] = *instance.KeyName
					}

					if instance.EbsOptimized != nil {
						metadata["aws/ebs-optimized"] = strconv.FormatBool(*instance.EbsOptimized)
					}

					if instance.EnaSupport != nil {
						metadata["aws/ena-support"] = strconv.FormatBool(*instance.EnaSupport)
					}

					if instance.SubnetId != nil {
						metadata["aws/subnet-id"] = *instance.SubnetId
						metadata["network/subnet-id"] = *instance.SubnetId
					}

					metadata["ctrlplane/links"] = fmt.Sprintf("{ \"AWS Console\": \"%s\" }", consoleUrl)

					// Get ARN for the instance
					arn := fmt.Sprintf("arn:aws:ec2:%s:%s:instance/%s", region, accountId, *instance.InstanceId)
					resources = append(resources, api.AgentResource{
						Version:    "compute/v1",
						Kind:       "Instance",
						Name:       name,
						Identifier: arn,
						Config:     instanceData.Struct(),
						Metadata:   metadata,
					})
				}
			}

			// Create or update resource provider
			if name == "" {
				name = fmt.Sprintf("aws-ec2-region-%s", region)
			}

			ctrlplaneClient, err := api.NewAPIKeyClientWithResponses(apiURL, apiKey)
			if err != nil {
				return fmt.Errorf("failed to create API client: %w", err)
			}

			rp, err := api.NewResourceProvider(ctrlplaneClient, workspaceId, name)
			if err != nil {
				return fmt.Errorf("failed to create resource provider: %w", err)
			}

			upsertResp, err := rp.UpsertResource(ctx, resources)
			log.Info("Response from upserting resources", "status", upsertResp.Status)
			if err != nil {
				return fmt.Errorf("failed to upsert resources: %w", err)
			}

			return cliutil.HandleResponseOutput(cmd, upsertResp)
		},
	}

	cmd.Flags().StringVarP(&name, "provider", "p", "", "Name of the resource provider")
	cmd.Flags().StringVarP(&region, "region", "c", "", "AWS Region")
	cmd.MarkFlagRequired("region")

	return cmd
}
