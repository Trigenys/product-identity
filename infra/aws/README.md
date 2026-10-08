# Product Identity on AWS

This directory owns the AWS runtime for the Product Identity API.

## Runtime boundary

Production target:

```text
GitHub Actions
  -> GitHub OIDC
  -> CloudFormation
  -> EC2 t4g.small (ARM64)
  -> SSM Run Command
  -> Docker / FastAPI
  -> Neon PostgreSQL
```

Cloudflare Pages remains the web frontend. The existing Cloudflare Worker is not
retired until the AWS runtime is database-ready and the public API route has
been switched.

## One-time AWS bootstrap

Deploy `github-oidc-bootstrap.yaml` once from an already authenticated AWS
session. No access key is stored in GitHub.

```bash
aws cloudformation deploy \
  --region us-east-1 \
  --stack-name product-identity-github-bootstrap \
  --template-file infra/aws/github-oidc-bootstrap.yaml \
  --capabilities CAPABILITY_NAMED_IAM
```

If the AWS account already has the GitHub Actions OIDC provider, pass its ARN:

```bash
--parameter-overrides \
  ExistingGitHubOidcProviderArn=arn:aws:iam::<account-id>:oidc-provider/token.actions.githubusercontent.com
```

Read the `DeployRoleArn` stack output and save it as the repository variable
`PRODUCT_IDENTITY_AWS_DEPLOY_ROLE_ARN`.

Optional repository variables:

- `PRODUCT_IDENTITY_AWS_REGION` — defaults to `eu-central-1`.
- `PRODUCT_IDENTITY_AWS_ENABLE_PUBLIC_IPV4` — defaults to `false`.
  Keep it false unless IPv4-only egress is proven necessary, because public
  IPv4 can create AWS charges.

## Runtime configuration in SSM

The EC2 instance reads runtime settings from:

```text
/product-identity/production/*
```

Each final path component is mapped to a `PRODUCT_IDENTITY_*` environment
variable. For example:

```text
/product-identity/production/DATABASE_URL
  -> PRODUCT_IDENTITY_DATABASE_URL
```

The production database URL must be a direct Neon PostgreSQL connection string
appropriate for a normal server runtime. Store credentials as `SecureString`;
never commit them.

Minimum gate for the first AWS runtime proof:

```bash
aws ssm put-parameter \
  --region eu-central-1 \
  --name /product-identity/production/DATABASE_URL \
  --type SecureString \
  --value '<NEON_DATABASE_URL>' \
  --overwrite
```

Before public cutover, also seed the production values required by the enabled
features, including authentication, verification/proof secrets, object storage,
and Shopify credentials. Use the names from `backend/.env.example`.

## Release behavior

`.github/workflows/aws-deploy.yml`:

1. assumes the AWS deployment role through GitHub OIDC;
2. builds a Linux/ARM64 production image;
3. publishes it to ECR Public;
4. deploys or updates the EC2 CloudFormation stack;
5. waits for the instance to become SSM-online;
6. executes `deploy-ec2.sh` through SSM;
7. fetches SecureString runtime configuration on-host;
8. runs `alembic upgrade head`;
9. starts the FastAPI container;
10. requires `/ready` to execute `SELECT 1` successfully.

If the OIDC role variable is absent, the workflow performs no AWS mutation and
finishes with a bootstrap-required summary.

## Cost guardrails

The application stack intentionally has no NAT Gateway, ALB/ELB, Elastic IP,
RDS, Secrets Manager, or SSH ingress. CI rejects those resources if they are
added accidentally. CPU credits are set to `standard`, and public IPv4 is
opt-in.
