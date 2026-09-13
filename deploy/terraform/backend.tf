# State lives in the bucket that bootstrap/ creates. The bucket name contains
# the account ID, so it is passed at init instead of committed. Locally,
# `python deploy/ops.py init` passes it. CI passes vars.TF_STATE_BUCKET.
# S3 writes a lock file next to the state, so there is no DynamoDB lock table.
terraform {
  backend "s3" {
    key          = "ops/terraform.tfstate"
    region       = "us-west-2"
    encrypt      = true
    use_lockfile = true
  }
}
