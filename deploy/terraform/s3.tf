# The private copy of the vault. The desktop sync writes vault/ and eval/, the
# node reads them, and nothing else gets in.
resource "aws_s3_bucket" "vault" {
  #checkov:skip=CKV_AWS_21:No versioning on purpose. A note the sync refuses or deletes has to leave the bucket, and an old version would keep it.
  #checkov:skip=CKV_AWS_18:Access logs need a second bucket. Only the node role reads this one and only the sync user writes to it.
  #checkov:skip=CKV_AWS_144:Replicating to another region doubles the copies of private notes. One desktop sync rebuilds this bucket.
  #checkov:skip=CKV_AWS_145:SSE-S3 encrypts at rest for free. KMS adds request costs and key grants without changing who can read.
  #checkov:skip=CKV2_AWS_62:Nothing listens for bucket events. The indexer pulls on a schedule.
  bucket = local.vault_bucket
}

resource "aws_s3_bucket_public_access_block" "vault" {
  bucket = aws_s3_bucket.vault.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "vault" {
  bucket = aws_s3_bucket.vault.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "vault_bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.vault.arn, "${aws_s3_bucket.vault.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "vault" {
  bucket = aws_s3_bucket.vault.id
  policy = data.aws_iam_policy_document.vault_bucket.json
}

resource "aws_s3_bucket_lifecycle_configuration" "vault" {
  bucket = aws_s3_bucket.vault.id

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    filter {}

    # A sync cut off mid-upload leaves parts that are billed but never listed.
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}
