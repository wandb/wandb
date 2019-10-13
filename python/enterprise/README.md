# Enterprise

W&B Enterprise is the on-prem version of [Weights & Biases](https://docs.wandb.com/enterprise/app.wandb.ai). It makes collaborative experiment tracking possible for enterprise machine learning teams, giving you a way to keep all training data and metadata within your organization's network.

[Request a demo to try out W&B Enterprise →](https://www.wandb.com/demo)

Most enterprise customers will use a [W&B Enterprise Server](https://docs.wandb.com/enterprise/server/about). This is a single virtual machine containing all of W&B's systems and storage. You can provision a W&B server on any cloud environment or local hardware or virtual server.

We also offer [W&B Enterprise Cloud](https://docs.wandb.com/enterprise/cloud/about), which runs a completely scalable infrastructure within your company's AWS or GCP account. This system can scale to any level of usage.

### Features

* Unlimited runs, experiments, and reports
* Keep your data safe on your own company's network
* Integrate with your company's authentication system
* Premier support by the W&B engineering team

The Enterprise Server consists of a single virtual machine, saved as a bootable image in the format of your cloud platform. Your W&B data is saved on a separate drive from the server softare so data can be preserved across VM versions.

We support the following environments:

| **Platform** | **Image Format** |
| :--- | :--- |
| Amazon Web Services | AMI |
| Microsoft Azure | Managed Image |
| Google Cloud Platform | GCE Image |
| VMware | OVA |
| Virtualbox | OVA |
| Vagrant | Vagrant Box |

#### Server Requirements

The W&B Enterprise server requires a virtual machine with at least 4 cores and 16GB memory.

