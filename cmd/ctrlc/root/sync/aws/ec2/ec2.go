package ec2

import (
	"context"
	"encoding/json"
	"fmt"
	"os"

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

type EC2Instance struct {
	ID          string            `json:"id"`
	Name        string            `json:"name"`
	Type        string            `json:"type"`
	State       string            `json:"state"`
	PrivateIP   string            `json:"privateIp"`
	PublicIP    string            `json:"publicIp,omitempty"`
	VpcID       string            `json:"vpcId"`
	SubnetID    string            `json:"subnetId"`
	Region      string            `json:"region"`
	LaunchTime  string            `json:"launchTime"`
}

func (t *EC2Instance) Struct() map[string]interface{} {
	b, _ := json.Marshal(t)
	var m map[string]interface{}
	json.Unmarshal(b, &m)
	return m
}

func NewSyncEC2Cmd() *cobra.Command {
	var configRegion string
	var name string
	cmd := &cobra.Command{
		Use:   "aws-ec2",
		Short: "Sync AWS EC2 instances into Ctrlplane",
		Example: heredoc.Doc(`
			# Make sure AWS credentials are configured via environment variables or ~/.aws/credentials
			
			# Sync all EC2 instances from a region
			$ ctrlc sync ec2 --config-region us-west-2 --workspace 2a7c5560-75c9-4dbe-be74-04ee33bf8188
		`),
		PreRunE: func(cmd *cobra.Command, args []string) error {
			if configRegion == "" {
				return fmt.Errorf("region is required")
			}
			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			log.Info("Syncing EC2 instances into Ctrlplane", "config-region", configRegion)

			
			ctx := context.Background()
			cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(configRegion))
			if err != nil {
				return fmt.Errorf("failed to load AWS config: %w", err)
			}

			credentials, err := cfg.Credentials.Retrieve(ctx)
			if err != nil {
				return fmt.Errorf("failed to retrieve AWS credentials: %w", err)
			}

			log.Info("AWS credentials loaded successfully", 
				"provider", credentials.Source,
				"region", configRegion,
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
						ID:         *instance.InstanceId,
						Name:       name,
						Type:       string(instance.InstanceType),
						State:      string(instance.State.Name),
						VpcID:      *instance.VpcId,
						SubnetID:   *instance.SubnetId,
						Region:     region,
						LaunchTime: instance.LaunchTime.String(),
					}

					if instance.PrivateIpAddress != nil {
						instanceData.PrivateIP = *instance.PrivateIpAddress
					}
					if instance.PublicIpAddress != nil {
						instanceData.PublicIP = *instance.PublicIpAddress
					}

					// Add AWS Console URL for the instance
					consoleUrl := fmt.Sprintf("https://%s.console.aws.amazon.com/ec2/home?region=%s#InstanceDetails:instanceId=%s",
						region,
						region,
						*instance.InstanceId)

					metadata := tags
					metadata["ec2/id"] = instanceData.ID
					metadata["ec2/type"] = instanceData.Type
					metadata["ec2/state"] = instanceData.State
					metadata["ec2/vpc"] = instanceData.VpcID
					metadata["ec2/subnet"] = instanceData.SubnetID
					metadata["ec2/region"] = instanceData.Region
					metadata["ec2/launch-time"] = instanceData.LaunchTime
					metadata["aws/account-id"] = accountId
					metadata["ctrlplane/links"] = fmt.Sprintf("{ \"AWS Console\": \"%s\" }", consoleUrl)

					// Get ARN for the instance
					arn := fmt.Sprintf("arn:aws:ec2:%s:%s:instance/%s", region, accountId, *instance.InstanceId)
					resources = append(resources, api.AgentResource{
						Version:    "aws/v1",
						Kind:       "EC2Instance",
						Name:       name,
						Identifier: arn,
						Config:     instanceData.Struct(),
						Metadata:   metadata,
					})
				}
			}
			
			// Create or update resource provider
			if name == "" {
				name = fmt.Sprintf("aws-ec2-config-region-%s", configRegion)
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
	cmd.Flags().StringVarP(&configRegion, "config-region", "c", "", "AWS Config Region")
	cmd.MarkFlagRequired("config-region")

	return cmd
}

