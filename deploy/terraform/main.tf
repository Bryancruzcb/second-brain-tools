provider "aws" {
  region = local.region

  # Whatever credentials are loaded, refuse to touch any other account.
  allowed_account_ids = [var.account_id]

  default_tags {
    tags = {
      Project = local.project
    }
  }
}

locals {
  project     = "second-brain-ops"
  region      = "us-west-2"
  github_repo = "Bryancruzcb/second-brain-tools"
  api_port    = 8000

  # Created by bootstrap/, which builds the same name.
  state_bucket = "second-brain-ops-tfstate-${var.account_id}"

  vault_bucket   = "second-brain-vault-${var.account_id}"
  vault_prefixes = ["vault/", "eval/"]
  deploys_table  = "second-brain-ops-deploys"
}
