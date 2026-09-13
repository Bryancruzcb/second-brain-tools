variable "account_id" {
  description = "AWS account ID. It names the buckets and keeps the provider off other accounts."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "The account_id value must be the 12-digit AWS account ID."
  }
}

variable "alert_email" {
  description = "Address that gets budget alerts and the SNS alert topic."
  type        = string
  sensitive   = true
}

variable "node_enabled" {
  description = "Whether the EC2 node exists. Turn it off between work sessions and everything else stays."
  type        = bool
  default     = false
}

variable "k3s_version" {
  description = "k3s release that cloud-init installs on the node."
  type        = string
  default     = "v1.36.4+k3s1"
}
