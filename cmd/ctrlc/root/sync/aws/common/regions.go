package common

import (
	"context"
	"fmt"
	"os"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials/stscreds"
	"github.com/aws/aws-sdk-go-v2/service/ec2"
	"github.com/aws/aws-sdk-go-v2/service/sts"
	"github.com/charmbracelet/log"
)

// A list of all AWS regions as fallback
var AllRegions = []string{
	"us-east-1", "us-east-2", "us-west-1", "us-west-2",
	"ap-south-1", "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
	"ap-southeast-1", "ap-southeast-2", "ap-southeast-3", "ap-east-1",
	"ca-central-1", "eu-central-1", "eu-west-1", "eu-west-2", "eu-west-3",
	"eu-north-1", "eu-south-1", "sa-east-1", "me-south-1", "af-south-1",
}

// GetRegions returns a list of regions to use based on the provided flags
func GetRegions(ctx context.Context, regions []string) ([]string, error) {
	if len(regions) > 0 {
		return regions, nil
	}

	// Dynamically discover available regions using EC2 API
	log.Info("No regions specified, discovering available regions...")

	// Load AWS config with default region to use for discovery
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion("us-east-1"))
	if err != nil {
		log.Warn("Failed to load AWS config for region discovery, using hardcoded list", "error", err)
		return AllRegions, nil
	}

	// Create EC2 client for region discovery
	ec2Client := ec2.NewFromConfig(cfg)

	// Call DescribeRegions to get all available regions
	resp, err := ec2Client.DescribeRegions(ctx, &ec2.DescribeRegionsInput{
		AllRegions: nil, // Set to true to include disabled regions
	})
	if err != nil {
		log.Warn("Failed to discover regions, using hardcoded list", "error", err)
		return AllRegions, nil
	}

	// Extract region names from response
	discoveredRegions := make([]string, 0, len(resp.Regions))
	for _, region := range resp.Regions {
		if region.RegionName != nil {
			discoveredRegions = append(discoveredRegions, *region.RegionName)
		}
	}

	if len(discoveredRegions) == 0 {
		log.Warn("No regions discovered, using hardcoded list")
		return AllRegions, nil
	}

	log.Info("Discovered AWS regions", "count", len(discoveredRegions))
	return discoveredRegions, nil
}

// GetAccountID retrieves the AWS account ID using the STS service
func GetAccountID(ctx context.Context, cfg aws.Config) (string, error) {
	stsClient := sts.NewFromConfig(cfg)
	result, err := stsClient.GetCallerIdentity(ctx, &sts.GetCallerIdentityInput{})
	if err != nil {
		return "", fmt.Errorf("failed to get AWS account ID: %w", err)
	}
	return *result.Account, nil
}

// InitAWSConfig initializes AWS config with the given region
func InitAWSConfig(ctx context.Context, region string) (aws.Config, error) {
	// Try to load AWS config with explicit credentials
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(region))
    if err != nil {
        log.Warn("LoadDefaultConfig failed, falling back to shared profile", "error", err)
        cfg, err = config.LoadDefaultConfig(ctx,
            config.WithRegion(region),
            config.WithSharedConfigProfile("default"),
        )
        if err != nil {
            return aws.Config{}, fmt.Errorf("failed to load AWS config: %w", err)
        }
    }
	
    if roleArn := os.Getenv("AWS_ROLE_ARN"); roleArn != "" {
        stsClient := sts.NewFromConfig(cfg)
        sessName := os.Getenv("AWS_ROLE_SESSION_NAME")
        if sessName == "" {
            sessName = "aws-sdk-go-session"
        }

        cfg.Credentials = aws.NewCredentialsCache(
            stscreds.NewAssumeRoleProvider(stsClient, roleArn, func(o *stscreds.AssumeRoleOptions) {
                o.RoleSessionName = sessName
                // o.Duration can be tweaked here if you need longer-lived tokens
            }),
        )
        log.Info("Configured STS AssumeRole", "role_arn", roleArn, "session", sessName)
    }


	// Verify credentials are valid before proceeding
	credentials, err := cfg.Credentials.Retrieve(ctx)
	if err != nil {
		return aws.Config{}, fmt.Errorf("failed to retrieve AWS credentials: %w", err)
	}

	log.Info("Successfully loaded AWS credentials", "region", region, "accessKeyId", credentials.AccessKeyID[:4]+"***")
	return cfg, nil
}
