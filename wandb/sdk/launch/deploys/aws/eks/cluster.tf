module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "19.0.4"

  cluster_name    = "launch-cluster"
  cluster_version = "1.24"

  vpc_id                         = "vpc-01d2697abae4329be"
  subnet_ids                     = ["subnet-0f4103ec0206c77e4", "subnet-08a71eb1965b0c081"]
  cluster_endpoint_public_access = true

  eks_managed_node_group_defaults = {
    ami_type = "AL2_x86_64"
  }

  eks_managed_node_groups = {
    one = {
      name           = "node-group-1"
      instance_types = ["t3.large"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
    }
    two = {
      name           = "node-group-2"
      instance_types = ["t3.large"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
    },
  }
}
