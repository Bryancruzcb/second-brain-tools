# The Grafana admin password. The generated value also sits in Terraform state.
# That is accepted because state lives in the private, encrypted, versioned
# bucket from bootstrap/, readable only by the owner and the Terraform roles.
resource "random_password" "grafana_admin" {
  length = 32

  # Letters and digits only, so Helm values and shell quoting pass it through untouched.
  special = false
}

resource "aws_ssm_parameter" "grafana_admin_password" {
  #checkov:skip=CKV_AWS_337:Uses the AWS-managed aws/ssm key. A customer-managed key costs a dollar a month, and the node role can only decrypt through SSM.
  name  = "/second-brain-ops/grafana-admin-password"
  type  = "SecureString"
  value = random_password.grafana_admin.result
}
