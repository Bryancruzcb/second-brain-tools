resource "aws_sns_topic" "alerts" {
  name = "second-brain-ops-alerts"

  # The AWS-managed key works when an IAM role in this account publishes.
  # CloudWatch alarms and Budgets can't publish under it and would need a
  # customer-managed key.
  kms_master_key_id = "alias/aws/sns"
}

# AWS emails a confirmation link, and nothing is delivered until it is clicked.
resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
