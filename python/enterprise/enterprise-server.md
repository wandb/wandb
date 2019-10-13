---
description: Setting up a W&B enterprise server to host results
---

# Enterprise Server

A W&B Enterprise Server is a self-contained virtual machine provisioned on your private cloud, a physical server, or developer workstation. See the following for instructions for how to provision a new instance.

### Amazon Web Services

Before you begin, make sure you have access to our AMI. You'll need to send us your AWS Account ID \(visible at your [Account Settings page](https://console.aws.amazon.com/billing/home?#/account)\) and desired region. W&B will share access to the W&B Enterprise Server AMI to your account and send you an AMI ID.

#### Launch the Instance

Go to EC2 &gt; Images &gt; AMIs in the AWS Console, select "Private images" in the search type dropdown, and search for "wandb". Select the last created image that appears, and click "Launch".

* **Choose Instance Type**: Make sure to select a `m5.2xlarge` instance or larger. W&B requires at least 4 cores and 16GB of memory.
* **Configure Instance**: If you plan to use a cloud file backend \(this is optional\), make sure your instance has an IAM role that allows it to access S3 and subscribe to SQS.
* **Add Storage**: If you plan on using the instance disk for file storage, be sure to provision the EBS disk with enough storage. The default is 300GB.
* **Configure Security Group**: Ensure that port 80 on your instance is accessible to any machine from which you want to run machine learning jobs, or to any IP range from which you plan to use the W&B web interface.

After launching your instance, wait for it to boot. Your instance will spin up and be accessible at port 80 at its public IP.

Your instance is usable from boot, but for advanced options, [you may now proceed to configuring your instance.](https://docs.wandb.com/enterprise/server/config)

#### Configuring instance availability

By default, your Enterprise Server serves the web interface and API on port 80 via unencrypted HTTP.

To add SSL, put your instance behind an Amazon Load Balancer and add a certificate, either by uploading it, or by using Amazon Certificate Manager.

To serve your instance from a hostname, configure your DNS nameservers to point towards the instance IP or Amazon Load Balancer.

If you are not serving your instance from a hostname, you should associate an Amazon Elastic IP with the machine so it remains accessible at a stable IP address.

### Google Cloud Platform

Before you begin, make sure you have access to our Compute Image.

#### Launch the Instance

Go to Compute Engine &gt; Images in the GCP console, and find the W&B image. Click "Create Instance".

* **Machine Type**: Make sure to select an `n2-standard-4` instance or larger. W&B requires at least 4 cores and 16GB of memory.
* **Identity and API Access**: If you plan on using a cloud file backend, be sure your instance service account has access to Google Storage and Pubsub.
* **Firewall**: Enable "Allow HTTP traffic".

After creating your instance, wait for it to boot. It will spin up and be accessible at port 80 at its public IP.

Your instance is usable from boot, but for advanced options, [you may now proceed to configuring your instance.](https://docs.wandb.com/enterprise/server/config)

#### Configuring instance availability

By default, your Enterprise Server serves the web interface and API on port 80 via unencrypted HTTP.

To add SSL, put your instance behind a Load Balancer and add a certificate using the Google console.

To serve your instance from a hostname, configure your DNS nameservers to point towards the instance IP or Google Load Balancer.

If you are not serving your instance from a hostname, you should associate an Elastic IP with the machine so it remains accessible at a stable IP address.

### Microsoft Azure

#### Authorize the W&B Azure App

First, you'll need to gain access to our shared image gallery through the "Weights And Biases On-Premises Images" Azure App.

CLI instructions:

```text
# First, install the azure CLI (`brew install azure-cli` on a Mac).

# Log in
az login

# Get the tenant ID.
TENANT_ID="$(az account show --query tenantId -o tsv)"

# Log into the W&B App Registry from your Azure account.
open "https://login.microsoftonline.com/$TENANT_ID/oauth2/authorize?client_id=af76df2c-ffe4-4f95-b71c-1558ed8afae1&response_type=code&redirect_uri=https%3A%2F%2Fwww.microsoft.com%2F"
```

Manual instructions:

* Navigate to [Portal.azure.com](http://portal.azure.com/) &gt; Azure Active Directory &gt; Properties. The directory ID it shows there is your Tenant ID. \([https://portal.azure.com/\#blade/Microsoft\_AAD\_IAM/ActiveDirectoryMenuBlade/Properties](https://portal.azure.com/#blade/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/Properties)\)
* Then, navigate to `https://login.microsoftonline.com/<Your Tenant ID>/oauth2/authorize?client_id=af76df2c-ffe4-4f95-b71c-1558ed8afae1&response_type=code&redirect_uri=https%3A%2F%2Fwww.microsoft.com%2F`
* Grant permissions. You'll be redirected to microsoft.com, at which point you can close the browser page.

#### Grant W&B App Permissions to your Resource Group

Then create a resource group and give this app permission to create a VM in that resource group.

* Create a Resource Group.
* Navigate to that Resource Group and then select Access control \(IAM\).
* Under Add role assignment select Add. Under Role, type Contributor.
* Under Assign access to:, leave this as Azure AD user, group, or service principal.
* Under Select, type "Weights And Biases On-Premises Images" then select it when it shows up in the list.
* When you are done, select Save.

#### Launch your VM

On Azure launching a VM from another tenant can only be done through the Azure CLI. \([See Microsoft's docs](https://docs.microsoft.com/en-us/azure/virtual-machines/linux/share-images-across-tenants)\)

```text
WB_IMAGES_APP_ID=af76df2c-ffe4-4f95-b71c-1558ed8afae1
WB_TENANT_ID=af722783-84b6-4adc-9c49-c792786eab4a

# Get this from our team
WB_IMAGES_SECRET=(Get this from the W&B Team)

# Customize these if needed
YOUR_TENANT_ID="$(az account show --query tenantId -o tsv)"
RESOURCE_GROUP_NAME="$(az group list --query '[0].name' -o tsv)"
VM_NAME="wandb-$(date +%Y-%m-%d)"
VM_IMAGE_RESOURCE_ID="/subscriptions/636d899d-58b4-4d7b-9e56-7a984388b4c8/resourceGroups/wandb-onprem-vm/providers/Microsoft.Compute/galleries/WandbAzureImages/images/WeightsAndBiasesOnPrem/versions/2019.9.25"
VM_SSH_ADMIN_USERNAME="azureadmin"

# Clear old credentials
az account clear

# Log in as service principle for W&B Tenant
az login --service-principal -u $WB_IMAGES_APP_ID -p $WB_IMAGES_SECRET --tenant $WB_TENANT_ID
az account get-access-token

# Log in as service principle for your tenant
az login --service-principal -u $WB_IMAGES_APP_ID -p $WB_IMAGES_SECRET --tenant $YOUR_TENANT_ID
az account get-access-token 

# Create the VM! You can customize this command per your requirements.
az vm create \
  --resource-group $RESOURCE_GROUP_NAME \
  --name $VM_NAME \
  --image $VM_IMAGE_RESOURCE_ID \
  --admin-username $VM_SSH_ADMIN_USERNAME \
  --generate-ssh-keys
```

Your W&B Server will be ready to use from moments of it booting up!

In the Azure console, you can now make sure port 80 on your instance is exposed to the network from which you'd like to access W&B.

For advanced options, [you may now proceed to configuring your instance.](https://docs.wandb.com/enterprise/server/config)

### VMWare

Contact the W&B team to gain access to the OVA file for the W&B Enterprise Server.

Once you have the file, in VMWare, go to File &gt; Import, and select the downloaded archive.

When creating your system, ensure to allocate at least 4 CPUs and 16GB of RAM if you intend to use this system for production workloads.

Your W&B Server will be ready to use from moments of it booting up!

In your VMWare Network preferences, make sure port 80 on your instance is exposed to the network from which you'd like to access W&B.

For advanced options, [you may now proceed to configuring your instance.](https://docs.wandb.com/enterprise/server/config)

### Virtualbox

Contact the W&B team to gain access to the OVA file for the W&B Enterprise Server.

Once you have the file, in Virtualbox, go to File &gt; Import Appliance, and select the downloaded archive.

When creating your system, ensure to allocate at least 4 CPUs and 16GB of RAM if you intend to use this system for production workloads.

Your W&B Server will be ready to use from moments of it booting up!

Once your VM is created, go to Settings &gt; Network &gt; Advanced &gt; Port Forwarding to forward port 80 on the guest machine to any desired port on the host.

For advanced options, [you may now proceed to configuring your instance.](https://docs.wandb.com/enterprise/server/config)

