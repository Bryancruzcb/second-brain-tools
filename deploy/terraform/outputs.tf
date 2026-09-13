output "node_instance_id" {
  description = "The EC2 node, or null while node_enabled is false."
  value       = one(aws_instance.node[*].id)
}

output "vault_bucket" {
  description = "Private bucket the desktop sync uploads to."
  value       = aws_s3_bucket.vault.bucket
}

output "terraform_plan_role_arn" {
  description = "Role that pull request plans assume."
  value       = aws_iam_role.github["terraform-plan"].arn
}

output "terraform_apply_role_arn" {
  description = "Role that applies on main assume."
  value       = aws_iam_role.github["terraform-apply"].arn
}

output "deploy_role_arn" {
  description = "Role the staging and prod deploy jobs assume."
  value       = aws_iam_role.github["deploy"].arn
}

output "alerts_topic_arn" {
  description = "SNS topic for alerts."
  value       = aws_sns_topic.alerts.arn
}

output "api_tunnel_command" {
  description = "Forwards localhost:8000 to the API on the node. Needs the Session Manager plugin. Null while the node is off."
  value = one([
    for id in aws_instance.node[*].id :
    "aws ssm start-session --region ${local.region} --target ${id} --document-name AWS-StartPortForwardingSession --parameters portNumber=${local.api_port},localPortNumber=${local.api_port}"
  ])
}
