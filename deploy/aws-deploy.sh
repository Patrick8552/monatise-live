#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
REPOSITORY="${MONATISE_ECR_REPOSITORY:-monatise}"
IMAGE_TAG="${MONATISE_IMAGE_TAG:-latest}"
IMAGE_PLATFORM="${MONATISE_IMAGE_PLATFORM:-linux/amd64}"
SERVICE_STACK="${MONATISE_SERVICE_STACK:-monatise-apprunner}"
SERVICE_NAME="${MONATISE_SERVICE_NAME:-monatise}"
ROLE_STACK="${MONATISE_ROLE_STACK:-monatise-apprunner-role}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v aws >/dev/null || {
  echo "aws CLI is required. Install and configure it first." >&2
  exit 1
}

DOCKER_BIN="${DOCKER_BIN:-}"
if [[ -z "${DOCKER_BIN}" ]]; then
  if command -v docker >/dev/null; then
    DOCKER_BIN="docker"
  elif [[ -x "/Applications/Docker.app/Contents/Resources/bin/docker" ]]; then
    DOCKER_BIN="/Applications/Docker.app/Contents/Resources/bin/docker"
  fi
fi

if [[ -z "${DOCKER_BIN}" ]]; then
  echo "docker is required. Install Docker Desktop first." >&2
  exit 1
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE_URI="${REGISTRY}/${REPOSITORY}:${IMAGE_TAG}"

aws cloudformation deploy \
  --region "${REGION}" \
  --stack-name "${ROLE_STACK}" \
  --template-file "${ROOT_DIR}/deploy/apprunner-access-role.yaml" \
  --no-fail-on-empty-changeset \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    HyperliquidAccountAddressSecretArn="${HYPERLIQUID_ACCOUNT_ADDRESS_SECRET_ARN:-}" \
    HyperliquidSecretKeySecretArn="${HYPERLIQUID_SECRET_KEY_SECRET_ARN:-}"

ACCESS_ROLE_ARN="$(aws cloudformation describe-stacks \
  --region "${REGION}" \
  --stack-name "${ROLE_STACK}" \
  --query "Stacks[0].Outputs[?OutputKey=='AccessRoleArn'].OutputValue" \
  --output text)"

INSTANCE_ROLE_ARN="$(aws cloudformation describe-stacks \
  --region "${REGION}" \
  --stack-name "${ROLE_STACK}" \
  --query "Stacks[0].Outputs[?OutputKey=='InstanceRoleArn'].OutputValue" \
  --output text)"

aws ecr describe-repositories \
  --region "${REGION}" \
  --repository-names "${REPOSITORY}" >/dev/null 2>&1 || \
aws ecr create-repository \
  --region "${REGION}" \
  --repository-name "${REPOSITORY}" \
  --image-scanning-configuration scanOnPush=true >/dev/null

aws ecr get-login-password --region "${REGION}" |
  "${DOCKER_BIN}" login --username AWS --password-stdin "${REGISTRY}"

"${DOCKER_BIN}" build --platform "${IMAGE_PLATFORM}" -f "${ROOT_DIR}/deploy/Dockerfile" -t "${REPOSITORY}:${IMAGE_TAG}" "${ROOT_DIR}"
"${DOCKER_BIN}" tag "${REPOSITORY}:${IMAGE_TAG}" "${IMAGE_URI}"
"${DOCKER_BIN}" push "${IMAGE_URI}"

aws cloudformation deploy \
  --region "${REGION}" \
  --stack-name "${SERVICE_STACK}" \
  --template-file "${ROOT_DIR}/deploy/apprunner.yaml" \
  --no-fail-on-empty-changeset \
  --parameter-overrides \
    ServiceName="${SERVICE_NAME}" \
    ImageIdentifier="${IMAGE_URI}" \
    AccessRoleArn="${ACCESS_ROLE_ARN}" \
    InstanceRoleArn="${INSTANCE_ROLE_ARN}" \
    RuntimeMode="${MONATISE_MODE:-paper}" \
    RuntimeNetwork="${MONATISE_NETWORK:-testnet}" \
    Symbol="${MONATISE_SYMBOL:-BTC}" \
    ExecutionMode="${MONATISE_EXECUTION_MODE:-dry_run}" \
    OrderQuoteSize="${MONATISE_ORDER_QUOTE_SIZE:-250}" \
    MaxOrderNotional="${MONATISE_MAX_ORDER_NOTIONAL:-250}" \
    MaxTotalNotional="${MONATISE_MAX_TOTAL_NOTIONAL:-1500}" \
    MaxBaseInventory="${MONATISE_MAX_BASE_INVENTORY:-0.1}" \
    MaxDailyLoss="${MONATISE_MAX_DAILY_LOSS:-100}" \
    MaxMarkMovePct="${MONATISE_MAX_MARK_MOVE_PCT:-0.03}" \
    MaxPositionValue="${MONATISE_MAX_POSITION_VALUE:-1000}" \
    MinAccountValue="${MONATISE_MIN_ACCOUNT_VALUE:-0}" \
    OrderRefreshSeconds="${MONATISE_ORDER_REFRESH_SECONDS:-30}" \
    AllowLiveOrders="${MONATISE_ALLOW_LIVE_ORDERS:-false}" \
    LiveConfirmation="${MONATISE_LIVE_CONFIRMATION:-}" \
    HyperliquidAccountAddressSecretArn="${HYPERLIQUID_ACCOUNT_ADDRESS_SECRET_ARN:-}" \
    HyperliquidSecretKeySecretArn="${HYPERLIQUID_SECRET_KEY_SECRET_ARN:-}"

SERVICE_URL="$(aws cloudformation describe-stacks \
  --region "${REGION}" \
  --stack-name "${SERVICE_STACK}" \
  --query "Stacks[0].Outputs[?OutputKey=='ServiceUrl'].OutputValue" \
  --output text)"

echo "Monatise deployed: https://${SERVICE_URL}"
