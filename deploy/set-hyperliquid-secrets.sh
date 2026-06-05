#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_SECRET_NAME="${HYPERLIQUID_ACCOUNT_ADDRESS_SECRET_NAME:-/monatise/hyperliquid/account-address}"
KEY_SECRET_NAME="${HYPERLIQUID_SECRET_KEY_SECRET_NAME:-/monatise/hyperliquid/secret-key}"

command -v aws >/dev/null || {
  echo "aws CLI is required. Install and configure it first." >&2
  exit 1
}

read -r -p "Hyperliquid account address: " ACCOUNT_ADDRESS
read -r -s -p "Hyperliquid API wallet private key: " SECRET_KEY
echo

if [[ -z "${ACCOUNT_ADDRESS}" || -z "${SECRET_KEY}" ]]; then
  echo "Both Hyperliquid values are required." >&2
  exit 1
fi

upsert_secret() {
  local name="$1"
  local value="$2"

  if aws secretsmanager describe-secret --region "${REGION}" --secret-id "${name}" >/dev/null 2>&1; then
    printf '%s' "${value}" |
      aws secretsmanager put-secret-value \
        --region "${REGION}" \
        --secret-id "${name}" \
        --secret-string file:///dev/stdin >/dev/null
  else
    printf '%s' "${value}" |
      aws secretsmanager create-secret \
        --region "${REGION}" \
        --name "${name}" \
        --secret-string file:///dev/stdin >/dev/null
  fi
}

upsert_secret "${ACCOUNT_SECRET_NAME}" "${ACCOUNT_ADDRESS}"
upsert_secret "${KEY_SECRET_NAME}" "${SECRET_KEY}"

ACCOUNT_SECRET_ARN="$(aws secretsmanager describe-secret \
  --region "${REGION}" \
  --secret-id "${ACCOUNT_SECRET_NAME}" \
  --query ARN \
  --output text)"

KEY_SECRET_ARN="$(aws secretsmanager describe-secret \
  --region "${REGION}" \
  --secret-id "${KEY_SECRET_NAME}" \
  --query ARN \
  --output text)"

echo "Stored Hyperliquid secrets in AWS Secrets Manager."
echo
echo "Use these for deployment:"
echo "export HYPERLIQUID_ACCOUNT_ADDRESS_SECRET_ARN='${ACCOUNT_SECRET_ARN}'"
echo "export HYPERLIQUID_SECRET_KEY_SECRET_ARN='${KEY_SECRET_ARN}'"
