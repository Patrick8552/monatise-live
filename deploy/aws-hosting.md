# Hosting Monatise On AWS

This deployment uses AWS App Runner with a Docker image stored in Amazon ECR.

## Why App Runner

Monatise is currently one container with one HTTP service. App Runner gives it managed HTTPS, health checks, logs, scaling, and container hosting without maintaining EC2 instances or a Kubernetes cluster.

## Prerequisites

- AWS account.
- AWS CLI installed and configured.
- Docker installed.
- IAM permissions for ECR, CloudFormation, IAM role creation, and App Runner.

If using a limited IAM user, attach the policy in `deploy/aws-deployment-policy.json` to the deployment user before running the deploy script.

## Deploy

```bash
AWS_REGION=us-east-1 ./deploy/aws-deploy.sh
```

If a previous App Runner service is stuck in a failed state, deploy a fresh
service name and stack while the failed service is cleaned up:

```bash
MONATISE_SERVICE_STACK=monatise-apprunner-retry \
MONATISE_SERVICE_NAME=monatise-retry \
AWS_REGION=us-east-1 \
./deploy/aws-deploy.sh
```

The script will:

1. Create an App Runner ECR access role.
2. Create an ECR repository named `monatise` if it does not exist.
3. Build the Docker image.
4. Push the image to ECR.
5. Deploy an App Runner service.
6. Print the hosted HTTPS URL.

## Paper Mode

The default deployment is paper mode:

```bash
MONATISE_MODE=paper AWS_REGION=us-east-1 ./deploy/aws-deploy.sh
```

## Live Mode

Do not put private keys directly into the CloudFormation template, shell history, or `.env` files. Store Hyperliquid values in AWS Secrets Manager, then pass only the resulting secret ARNs into deployment.

Create or update the AWS secrets:

```bash
AWS_REGION=us-east-1 ./deploy/set-hyperliquid-secrets.sh
```

The script prints two `export` commands. Run those exports in the same terminal before deploying live mode.

Real orders still require:

- `MONATISE_MODE=live`
- `MONATISE_ALLOW_LIVE_ORDERS=true`
- `MONATISE_LIVE_CONFIRMATION=I_UNDERSTAND_REAL_MONEY`
- `HYPERLIQUID_ACCOUNT_ADDRESS_SECRET_ARN`
- `HYPERLIQUID_SECRET_KEY_SECRET_ARN`

Deploy live testnet only after reviewing the risk limits:

```bash
MONATISE_MODE=live \
MONATISE_NETWORK=testnet \
MONATISE_ALLOW_LIVE_ORDERS=true \
MONATISE_LIVE_CONFIRMATION=I_UNDERSTAND_REAL_MONEY \
AWS_REGION=us-east-1 \
./deploy/aws-deploy.sh
```

## Useful Commands

Get service URL:

```bash
aws cloudformation describe-stacks \
  --stack-name monatise-apprunner \
  --query "Stacks[0].Outputs[?OutputKey=='ServiceUrl'].OutputValue" \
  --output text
```

Delete the service:

```bash
aws cloudformation delete-stack --stack-name monatise-apprunner
```

Delete the access role:

```bash
aws cloudformation delete-stack --stack-name monatise-apprunner-role
```
