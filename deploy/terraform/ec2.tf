locals {
  instance_type = "m7i-flex.large"
}

data "aws_vpc" "default" {
  default = true
}

# Not every zone in the region offers every instance type.
data "aws_ec2_instance_type_offerings" "node" {
  location_type = "availability-zone"

  filter {
    name   = "instance-type"
    values = [local.instance_type]
  }
}

data "aws_subnets" "node" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }

  filter {
    name   = "availability-zone"
    values = data.aws_ec2_instance_type_offerings.node.locations
  }
}

# Canonical publishes the current Ubuntu 24.04 AMI ID under this public name.
data "aws_ssm_parameter" "ubuntu_ami" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

# Security groups don't filter the VPC DNS resolver or the time service, so
# those need no rules.
resource "aws_security_group" "node" {
  name        = "second-brain-ops-node"
  description = "No inbound rules. The owner and CI reach the node through SSM."
  vpc_id      = data.aws_vpc.default.id

  egress {
    description = "HTTPS to SSM, S3, GHCR, and GitHub"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "HTTP to the Ubuntu package mirrors"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "second-brain-ops-node"
  }
}

resource "aws_instance" "node" {
  #checkov:skip=CKV_AWS_88:The public IP carries outbound traffic only. The security group has no inbound rules, and a NAT gateway would cost more than the node.
  #checkov:skip=CKV_AWS_126:Detailed monitoring is billed per metric. Prometheus and node-exporter cover the node from week 3.
  count = var.node_enabled ? 1 : 0

  ami                         = data.aws_ssm_parameter.ubuntu_ami.insecure_value
  instance_type               = local.instance_type
  subnet_id                   = sort(data.aws_subnets.node.ids)[0]
  vpc_security_group_ids      = [aws_security_group.node.id]
  iam_instance_profile        = aws_iam_instance_profile.node.name
  associate_public_ip_address = true
  ebs_optimized               = true

  user_data = templatefile("${path.module}/cloud-init.yaml", {
    k3s_version = var.k3s_version
  })

  # cloud-init only runs on a fresh node, so a change to it has to replace the node.
  user_data_replace_on_change = true

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"

    # Pods sit one network hop behind the host. With a limit of 1, the indexer
    # CronJob couldn't get the instance role credentials it needs for S3.
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 30
    encrypted             = true
    delete_on_termination = true
  }

  lifecycle {
    # Canonical republishes the AMI often. Taking a new one only when the node
    # is recreated keeps an unrelated merge from replacing a running node.
    ignore_changes = [ami]
  }

  tags = {
    Name = "second-brain-ops-node"
  }
}
