# The budget was created by hand before anything else, so Terraform adopts it
# instead of creating a second one.
import {
  to = aws_budgets_budget.monthly
  id = "${var.account_id}:second-brain-ops-monthly"
}

resource "aws_budgets_budget" "monthly" {
  name         = "second-brain-ops-monthly"
  budget_type  = "COST"
  limit_amount = "15.0"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Credits and refunds stay out, so the budget tracks real usage even while
  # Free plan credits pay the bill.
  cost_types {
    include_credit             = false
    include_discount           = true
    include_other_subscription = true
    include_recurring          = true
    include_refund             = false
    include_subscription       = true
    include_support            = true
    include_tax                = true
    include_upfront            = true
    use_amortized              = false
    use_blended                = false
  }

  dynamic "notification" {
    for_each = [
      { type = "ACTUAL", percent = 50 },
      { type = "ACTUAL", percent = 100 },
      { type = "FORECASTED", percent = 100 },
    ]

    content {
      comparison_operator        = "GREATER_THAN"
      notification_type          = notification.value.type
      threshold                  = notification.value.percent
      threshold_type             = "PERCENTAGE"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}
