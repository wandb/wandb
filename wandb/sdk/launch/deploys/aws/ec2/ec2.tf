# Definition of variables and resources for AWS EC2 deployment
variable "region" {
  type    = string
  default = "us-east-2"
}

variable "profile" {
  type    = string
  default = "default"
}

variable "instance_type" {
  type    = string
  default = "t2.micro"
}

variable "subnet_id" {
  type = string
}

variable "security_group_id" {
  type = string
}

data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["amzn2-ami-hvm-*-x86_64-gp2"]
  }
}

provider "aws" {
  region = var.region
}

resource "aws_instance" "instance" {
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.security_group_id]
}
