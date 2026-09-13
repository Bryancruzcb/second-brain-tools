locals {
  # Built from names rather than resource attributes, so a plan shows each policy in full.
  state_bucket_arn   = "arn:aws:s3:::${local.state_bucket}"
  vault_bucket_arn   = "arn:aws:s3:::${local.vault_bucket}"
  deploys_table_arn  = "arn:aws:dynamodb:${local.region}:${var.account_id}:table/${local.deploys_table}"
  ops_parameters_arn = "arn:aws:ssm:${local.region}:${var.account_id}:parameter/second-brain-ops/*"
  ec2_arn            = "arn:aws:ec2:${local.region}:${var.account_id}"
  iam_arn            = "arn:aws:iam::${var.account_id}"

  # Which workflow runs may assume each GitHub role, by the token's sub claim.
  # Pull requests from forks get no token, so pull_request means this repo's branches.
  #
  # The deploy role waits for week 4 and deploy.yml. It can run commands as root
  # on the node, and it trusts the staging and prod environments. GitHub creates
  # an environment the first time any job names it, with no branch limits, so
  # the role only goes in after both environments are restricted to main.
  github_role_subjects = {
    terraform-plan  = ["repo:${local.github_repo}:pull_request"]
    terraform-apply = ["repo:${local.github_repo}:ref:refs/heads/main"]
  }
}

# ---------------------------------------------------------------------------
# The node

data "aws_iam_policy_document" "node_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "second-brain-ops-node"
  assume_role_policy = data.aws_iam_policy_document.node_trust.json
}

resource "aws_iam_role_policy_attachment" "node_ssm" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "node" {
  statement {
    sid       = "ListVault"
    actions   = ["s3:ListBucket"]
    resources = [local.vault_bucket_arn]
  }

  statement {
    sid       = "ReadVault"
    actions   = ["s3:GetObject"]
    resources = ["${local.vault_bucket_arn}/*"]
  }

  statement {
    sid       = "ReadOpsParameters"
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = [local.ops_parameters_arn]
  }

  statement {
    sid       = "DecryptParametersThroughSsm"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${local.region}:${var.account_id}:key/*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${local.region}.amazonaws.com"]
    }
  }

  statement {
    sid       = "RecordDeploys"
    actions   = ["dynamodb:PutItem"]
    resources = [local.deploys_table_arn]
  }
}

resource "aws_iam_role_policy" "node" {
  name   = "second-brain-ops-node"
  role   = aws_iam_role.node.id
  policy = data.aws_iam_policy_document.node.json
}

resource "aws_iam_instance_profile" "node" {
  name = "second-brain-ops-node"
  role = aws_iam_role.node.name
}

# ---------------------------------------------------------------------------
# The desktop sync. The owner creates its access key by hand, so the key
# never lands in state.

resource "aws_iam_user" "vault_sync" {
  #checkov:skip=CKV_AWS_273:The nightly desktop sync needs a long-lived key, and this account has no SSO. The owner rotates the key every 90 days.
  name = "second-brain-vault-sync"
}

data "aws_iam_policy_document" "vault_sync" {
  statement {
    sid       = "ListVault"
    actions   = ["s3:ListBucket"]
    resources = [local.vault_bucket_arn]
  }

  statement {
    sid       = "MirrorVault"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = [for prefix in local.vault_prefixes : "${local.vault_bucket_arn}/${prefix}*"]
  }
}

resource "aws_iam_user_policy" "vault_sync" {
  #checkov:skip=CKV_AWS_40:The user has a single job, so a group would only add a layer between it and its policy.
  name   = "second-brain-vault-sync"
  user   = aws_iam_user.vault_sync.name
  policy = data.aws_iam_policy_document.vault_sync.json
}

# ---------------------------------------------------------------------------
# GitHub Actions

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_trust" {
  for_each = local.github_role_subjects

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = each.value
    }
  }
}

resource "aws_iam_role" "github" {
  for_each = local.github_role_subjects

  name               = "second-brain-ops-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.github_trust[each.key].json
}

# Plans on pull requests.

resource "aws_iam_role_policy_attachment" "plan_read_only" {
  role       = aws_iam_role.github["terraform-plan"].name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "plan" {
  statement {
    sid       = "ListState"
    actions   = ["s3:ListBucket"]
    resources = [local.state_bucket_arn]
  }

  # Plans run with -lock=false, so reading the state is enough.
  statement {
    sid       = "ReadState"
    actions   = ["s3:GetObject"]
    resources = ["${local.state_bucket_arn}/ops/terraform.tfstate"]
  }

  # ReadOnlyAccess includes s3:Get* on every bucket, and a pull request from
  # any branch in this repo can assume this role. The notes stay off limits.
  statement {
    sid       = "NoVaultContent"
    effect    = "Deny"
    actions   = ["s3:GetObject*"]
    resources = ["${local.vault_bucket_arn}/*"]
  }
}

resource "aws_iam_role_policy" "plan" {
  name   = "second-brain-ops-terraform-plan"
  role   = aws_iam_role.github["terraform-plan"].id
  policy = data.aws_iam_policy_document.plan.json
}

# Applies on main. Scoped to what this stack manages. Anyone who can merge to
# main can still grant a second-brain-* role new permissions through this
# role, so branch protection on main is part of the boundary.

data "aws_iam_policy_document" "apply" {
  #checkov:skip=CKV_AWS_356:Only ec2:Describe* trips this. It is read-only, most EC2 Describe calls can't be scoped by resource, and a hand-kept list of the provider's calls would break applies when the provider adds one.
  statement {
    sid       = "ListState"
    actions   = ["s3:ListBucket"]
    resources = [local.state_bucket_arn]
  }

  statement {
    sid       = "WriteState"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${local.state_bucket_arn}/ops/terraform.tfstate"]
  }

  statement {
    sid       = "StateLock"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.state_bucket_arn}/ops/terraform.tfstate.tflock"]
  }

  # EC2 Describe calls don't support resource-level permissions.
  statement {
    sid       = "DescribeEc2"
    actions   = ["ec2:Describe*"]
    resources = ["*"]
  }

  statement {
    sid     = "LaunchNode"
    actions = ["ec2:RunInstances"]
    resources = [
      "arn:aws:ec2:${local.region}::image/*",
      "${local.ec2_arn}:instance/*",
      "${local.ec2_arn}:network-interface/*",
      "${local.ec2_arn}:security-group/*",
      "${local.ec2_arn}:subnet/*",
      "${local.ec2_arn}:volume/*",
    ]
  }

  statement {
    sid       = "CreateSecurityGroup"
    actions   = ["ec2:CreateSecurityGroup"]
    resources = ["${local.ec2_arn}:security-group/*", "${local.ec2_arn}:vpc/*"]
  }

  # EC2 IDs are random, so the Project tag ties EC2 resources to this stack.
  # Launch calls may tag, and changes after that need the tag.
  statement {
    sid       = "TagOnCreate"
    actions   = ["ec2:CreateTags"]
    resources = ["${local.ec2_arn}:instance/*", "${local.ec2_arn}:security-group/*", "${local.ec2_arn}:volume/*"]

    condition {
      test     = "StringEquals"
      variable = "ec2:CreateAction"
      values   = ["RunInstances", "CreateSecurityGroup"]
    }
  }

  statement {
    sid = "ManageTaggedEc2"
    actions = [
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:CreateTags",
      "ec2:DeleteSecurityGroup",
      "ec2:DeleteTags",
      "ec2:ModifyInstanceAttribute",
      "ec2:ModifyInstanceMetadataOptions",
      "ec2:RevokeSecurityGroupEgress",
      "ec2:StartInstances",
      "ec2:StopInstances",
      "ec2:TerminateInstances",
    ]
    resources = ["${local.ec2_arn}:instance/*", "${local.ec2_arn}:security-group/*", "${local.ec2_arn}:volume/*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [local.project]
    }
  }

  statement {
    sid       = "PassNodeRole"
    actions   = ["iam:PassRole"]
    resources = ["${local.iam_arn}:role/${aws_iam_role.node.name}"]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ec2.amazonaws.com"]
    }
  }

  statement {
    sid = "ManageRoles"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:DeleteRolePolicy",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
      "iam:PutRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:UpdateRole",
    ]
    resources = ["${local.iam_arn}:role/second-brain-*"]
  }

  # Only the two AWS managed policies this stack attaches.
  statement {
    sid       = "AttachKnownPolicies"
    actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
    resources = ["${local.iam_arn}:role/second-brain-*"]

    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values = [
        "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
        "arn:aws:iam::aws:policy/ReadOnlyAccess",
      ]
    }
  }

  statement {
    sid = "ManageInstanceProfile"
    actions = [
      "iam:AddRoleToInstanceProfile",
      "iam:CreateInstanceProfile",
      "iam:DeleteInstanceProfile",
      "iam:GetInstanceProfile",
      "iam:ListInstanceProfileTags",
      "iam:RemoveRoleFromInstanceProfile",
      "iam:TagInstanceProfile",
      "iam:UntagInstanceProfile",
    ]
    resources = ["${local.iam_arn}:instance-profile/second-brain-*"]
  }

  statement {
    sid = "ManageSyncUser"
    actions = [
      "iam:CreateUser",
      "iam:DeleteUser",
      "iam:DeleteUserPolicy",
      "iam:GetUser",
      "iam:GetUserPolicy",
      "iam:ListAccessKeys",
      "iam:ListAttachedUserPolicies",
      "iam:ListGroupsForUser",
      "iam:ListUserPolicies",
      "iam:ListUserTags",
      "iam:PutUserPolicy",
      "iam:TagUser",
      "iam:UntagUser",
    ]
    resources = ["${local.iam_arn}:user/second-brain-*"]
  }

  statement {
    sid = "ManageGithubOidc"
    actions = [
      "iam:AddClientIDToOpenIDConnectProvider",
      "iam:CreateOpenIDConnectProvider",
      "iam:DeleteOpenIDConnectProvider",
      "iam:GetOpenIDConnectProvider",
      "iam:ListOpenIDConnectProviderTags",
      "iam:RemoveClientIDFromOpenIDConnectProvider",
      "iam:TagOpenIDConnectProvider",
      "iam:UntagOpenIDConnectProvider",
      "iam:UpdateOpenIDConnectProviderThumbprint",
    ]
    resources = ["${local.iam_arn}:oidc-provider/token.actions.githubusercontent.com"]
  }

  # Bucket-level calls only. No object ARN is listed, so this role can't read notes.
  statement {
    sid = "ManageVaultBucket"
    actions = [
      "s3:CreateBucket",
      "s3:DeleteBucket",
      "s3:DeleteBucketPolicy",
      "s3:Get*",
      "s3:ListBucket",
      "s3:PutBucketPolicy",
      "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketTagging",
      "s3:PutEncryptionConfiguration",
      "s3:PutLifecycleConfiguration",
    ]
    resources = [local.vault_bucket_arn]
  }

  statement {
    sid = "ManageOpsParameters"
    actions = [
      "ssm:AddTagsToResource",
      "ssm:DeleteParameter",
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:ListTagsForResource",
      "ssm:PutParameter",
      "ssm:RemoveTagsFromResource",
    ]
    resources = [local.ops_parameters_arn]
  }

  statement {
    sid       = "ReadUbuntuAmiId"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${local.region}::parameter/aws/service/canonical/*"]
  }

  # DescribeParameters doesn't support resource-level permissions.
  statement {
    sid       = "DescribeParameters"
    actions   = ["ssm:DescribeParameters"]
    resources = ["*"]
  }

  statement {
    sid = "ManageDeploysTable"
    actions = [
      "dynamodb:CreateTable",
      "dynamodb:DeleteTable",
      "dynamodb:DescribeContinuousBackups",
      "dynamodb:DescribeTable",
      "dynamodb:DescribeTimeToLive",
      "dynamodb:ListTagsOfResource",
      "dynamodb:TagResource",
      "dynamodb:UntagResource",
      "dynamodb:UpdateContinuousBackups",
      "dynamodb:UpdateTable",
    ]
    resources = [local.deploys_table_arn]
  }

  statement {
    sid = "ManageBudget"
    actions = [
      "budgets:ListTagsForResource",
      "budgets:ModifyBudget",
      "budgets:TagResource",
      "budgets:UntagResource",
      "budgets:ViewBudget",
    ]
    resources = ["arn:aws:budgets::${var.account_id}:budget/second-brain-ops-monthly"]
  }

  statement {
    sid = "ManageAlertsTopic"
    actions = [
      "sns:CreateTopic",
      "sns:DeleteTopic",
      "sns:GetSubscriptionAttributes",
      "sns:GetTopicAttributes",
      "sns:ListSubscriptionsByTopic",
      "sns:ListTagsForResource",
      "sns:SetSubscriptionAttributes",
      "sns:SetTopicAttributes",
      "sns:Subscribe",
      "sns:TagResource",
      "sns:Unsubscribe",
      "sns:UntagResource",
    ]
    # Subscription ARNs start with the topic ARN, so this covers them too.
    resources = ["arn:aws:sns:${local.region}:${var.account_id}:second-brain-ops-alerts*"]
  }
}

resource "aws_iam_role_policy" "apply" {
  name   = "second-brain-ops-terraform-apply"
  role   = aws_iam_role.github["terraform-apply"].id
  policy = data.aws_iam_policy_document.apply.json
}
