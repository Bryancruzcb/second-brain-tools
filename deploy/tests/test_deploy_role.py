"""The deploy role runs commands as root on the node, so these tests read
iam.tf as text and pin what it may do. No terraform binary and no AWS call:
the point is that a later edit that widens the role fails here first.
"""

import re
from pathlib import Path

import pytest

TERRAFORM = Path(__file__).resolve().parents[1] / "terraform"
IAM = (TERRAFORM / "iam.tf").read_text(encoding="utf-8")
MAIN = (TERRAFORM / "main.tf").read_text(encoding="utf-8")

# The immutable subject, which carries the numeric owner and repository ids.
# A role that trusts repo:Bryancruzcb/second-brain-tools instead never matches
# any token this repo gets, which is how CI broke once already.
OIDC_SUBJECT = re.search(r'github_oidc_subject\s*=\s*"([^"]+)"', MAIN).group(1)
NAME_ONLY_SUBJECT = "repo:Bryancruzcb/second-brain-tools"


def block(header: str) -> str:
    """One top-level block's body. Every line inside it is indented, so the
    block ends at the first closing brace in column zero."""
    body = re.search(rf"^{re.escape(header)} \{{\n(.*?)\n\}}$", IAM, re.DOTALL | re.MULTILINE)
    assert body, f"no {header} block in iam.tf"
    return body.group(1)


def tf_list(text: str, key: str) -> list[str]:
    """One Terraform list's items as written, with quotes stripped. Items that
    are expressions rather than strings, such as local.deploys_table_arn, come
    back as their source text."""
    items = re.search(rf"\b{key}\s*=\s*\[(.*?)\]", text, re.DOTALL)
    assert items, f"no {key} list in:\n{text}"
    return [item.strip().strip('"') for item in items.group(1).split(",") if item.strip()]


def statements(document: str) -> dict[str, str]:
    """The statements of an aws_iam_policy_document, by sid."""
    found = re.findall(r"^  statement \{\n(.*?)\n  \}$", document, re.DOTALL | re.MULTILINE)
    return {re.search(r'sid\s*=\s*"([^"]+)"', chunk).group(1): chunk for chunk in found}


DEPLOY_POLICY = statements(block('data "aws_iam_policy_document" "deploy"'))
DEPLOY_SUBJECTS = [
    subject.replace("${local.github_oidc_subject}", OIDC_SUBJECT)
    for subject in tf_list(block("locals"), "deploy")
]


def test_the_role_trusts_both_github_environments():
    """deploy.yml's jobs name an environment, so their tokens carry
    :environment:<name> and never the branch ref."""
    assert DEPLOY_SUBJECTS == [
        f"{OIDC_SUBJECT}:environment:staging",
        f"{OIDC_SUBJECT}:environment:prod",
    ]


def test_every_trusted_subject_carries_the_numeric_ids():
    for subject in DEPLOY_SUBJECTS:
        assert re.match(r"^repo:[^/@]+@\d+/[^/@]+@\d+:", subject), subject


def test_no_role_trusts_the_name_only_subject():
    assert NAME_ONLY_SUBJECT not in OIDC_SUBJECT
    assert NAME_ONLY_SUBJECT not in IAM


def test_send_command_is_limited_to_the_node_and_one_document():
    resources = tf_list(DEPLOY_POLICY["RunCommandsOnTheNode"], "resources")
    assert "*" not in resources
    instances, document = resources
    assert instances.endswith(":instance/*")
    assert document.endswith(":document/AWS-RunShellScript")


@pytest.mark.parametrize("action", ["s3:", "kms:", "ssm:StartSession"])
def test_the_policy_grants_nothing_of(action):
    """The node reads the vault and the dataset with its own instance role, and
    an interactive session would turn starting a workflow into a root shell."""
    for sid, chunk in DEPLOY_POLICY.items():
        assert action not in chunk, sid


def test_only_the_deploys_table_is_writable():
    for sid, chunk in DEPLOY_POLICY.items():
        if any(action.startswith("dynamodb:") for action in tf_list(chunk, "actions")):
            assert tf_list(chunk, "resources") == ["local.deploys_table_arn"], sid


def test_the_policy_is_attached_to_the_deploy_role():
    attachment = block('resource "aws_iam_role_policy" "deploy"')
    assert 'role   = aws_iam_role.github["deploy"].id' in attachment
    assert "policy = data.aws_iam_policy_document.deploy.json" in attachment
