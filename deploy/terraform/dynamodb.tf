# One item per deploy. The pipeline writes history here so main never gets bot commits.
resource "aws_dynamodb_table" "deploys" {
  #checkov:skip=CKV_AWS_119:Encrypted with the AWS-managed DynamoDB key. The items are commit SHAs and scores, and a customer-managed key costs a dollar a month.
  name         = local.deploys_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "sha"
  range_key    = "deployed_at"

  attribute {
    name = "sha"
    type = "S"
  }

  attribute {
    name = "deployed_at"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }

  point_in_time_recovery {
    enabled = true
  }
}
