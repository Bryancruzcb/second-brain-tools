# Used for both stacks. From deploy/terraform:
#   tflint --init
#   tflint --var=node_enabled=true
#   tflint --chdir=bootstrap --config="$PWD/.tflint.hcl"
# tflint skips a resource whose count is 0, so the main stack needs
# node_enabled=true for the node to be linted.
plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.48.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}
