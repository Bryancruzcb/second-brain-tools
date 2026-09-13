# Creates the bucket that holds the main stack's state. This stack keeps its
# own state on local disk, because it can't use a bucket it hasn't made yet.
# Run it once per account: python deploy/ops.py bootstrap

terraform {
  required_version = "~> 1.16"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.64"
    }
  }
}

variable "account_id" {
  description = "AWS account ID. It names the bucket and keeps the provider off other accounts."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "The account_id value must be the 12-digit AWS account ID."
  }
}

provider "aws" {
  region              = "us-west-2"
  allowed_account_ids = [var.account_id]

  default_tags {
    tags = {
      Project = "second-brain-ops"
    }
  }
}

resource "aws_s3_bucket" "state" {
  #checkov:skip=CKV_AWS_18:Access logs need a second bucket. Only the owner and the Terraform roles touch state.
  #checkov:skip=CKV_AWS_144:Versioning already keeps old state. A second region doubles the copies of a file that holds a password.
  #checkov:skip=CKV_AWS_145:SSE-S3 encrypts at rest for free. KMS adds request costs and key grants without changing who can read.
  #checkov:skip=CKV2_AWS_62:Nothing listens for state bucket events.
  bucket = "second-brain-ops-tfstate-${var.account_id}"

  # Losing this bucket loses track of everything the main stack built.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "expire-old-state"
    status = "Enabled"

    filter {}

    # Every apply and every lock file leaves a noncurrent version behind.
    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  # A noncurrent-version rule needs versioning to be on first.
  depends_on = [aws_s3_bucket_versioning.state]
}

output "state_bucket" {
  description = "Bucket to pass to the main stack at init. ops.py init builds the same name."
  value       = aws_s3_bucket.state.bucket
}
