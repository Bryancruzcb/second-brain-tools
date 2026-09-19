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
  project = "second-brain-ops"
  region  = "us-west-2"
  # This repo's OIDC tokens carry GitHub's immutable subject: owner and
  # repository by numeric id as well as name, so a renamed or recreated repo
  # with the same name can't assume the roles. The repo's claim template has
  # use_immutable_subject on; check it with
  #   gh api repos/Bryancruzcb/second-brain-tools/actions/oidc/customization/sub
  # The name-only form (repo:Bryancruzcb/second-brain-tools) never matches.
  github_oidc_subject = "repo:Bryancruzcb@209073313/second-brain-tools@1302144502"
  api_port            = 8000
  # Staging's API service, pinned in deploy/k8s/overlays/staging/service-ip.yaml.
  staging_service_ip = "10.43.0.80"

  # Created by bootstrap/, which builds the same name.
  state_bucket = "second-brain-ops-tfstate-${var.account_id}"

  vault_bucket   = "second-brain-vault-${var.account_id}"
  vault_prefixes = ["vault/", "eval/"]
  deploys_table  = "second-brain-ops-deploys"
}
