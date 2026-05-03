# Setup

The backend setup script provisions the remote infrastructure used by the local Kirana prototype. Run it from `backend/` after installing dependencies with `uv`.

```sh
cd backend
uv sync
uv run python setup.py
```

## Required `.env`

Create `backend/.env` with:

```dotenv
CLOUDFLARE_API_TOKEN=<cloudflare-api-token>
CLOUDFLARE_ACCOUNT_ID=<cloudflare-account-id>
AWS_ACCESS_KEY_ID=<tigris-access-key-id>
AWS_SECRET_ACCESS_KEY=<tigris-secret-access-key>

# Required after enabling Authenticated Gateway in the Cloudflare dashboard.
CLOUDFLARE_AI_GATEWAY_API_TOKEN=<cloudflare-ai-gateway-auth-token>

# Optional if the D1 database already exists.
# setup.py writes this after creating the database.
KIRANA_DB_ID=<d1-database-id>
```

`setup.py` creates the AI Gateway resource, but it does not enable gateway authentication or create provider keys. Those are dashboard steps described below.

## Where Credentials Come From

- `CLOUDFLARE_API_TOKEN`: Cloudflare dashboard -> My Profile -> API Tokens. The token needs access to create/manage D1, Vectorize, and AI Gateway resources for the account.
- `CLOUDFLARE_ACCOUNT_ID`: Cloudflare dashboard -> account page/sidebar, or the account URL in the dashboard.
- `CLOUDFLARE_AI_GATEWAY_API_TOKEN`: Cloudflare AI Gateway authentication token created from the gateway settings page after `setup.py` creates the gateway.
- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`: Tigris dashboard access keys. The setup uses Tigris' S3-compatible API endpoint from `backend/config.toml`.
- `KIRANA_DB_ID`: Cloudflare D1 database UUID. Leave unset for a fresh setup; the script creates the D1 database and appends the generated ID to `.env`.

## Resources Created

The concrete resource names are defined in `backend/config.toml`.

### Cloudflare D1

Creates or reuses the `kirana` D1 database.

The setup creates these tables:

- `splits`: imported Splitwise rows and per-person payment amounts.
- `receipts`: structured receipt-level data and the eventual object-store image URL.
- `receipt_items`: item-level receipt rows linked to `receipts`.

It also creates indexes for receipt date lookup, receipt item joins, and item-name search.

### Cloudflare Vectorize

Creates the `kirana-reciept-summaries` Vectorize index with:

- dimensions: `1536`
- distance metric: `cosine`
- intended embedding model: `qwen3-vl-embedding-2b`

The index stores receipt summary embeddings and is intended to share the same embedding space with query-time pantry or item images.

### Vectorize Metadata Indices

Creates metadata indices used for filtering and joining retrieved vectors back to structured data:

- `receipt_id` as `number`
- `store_name` as `string`
- `date` as `number`

`receipt_id` is the main join key back to D1 receipts and to the corresponding object filename.

### Cloudflare AI Gateway

Creates the `kirana-ai-gateway` AI Gateway with logging enabled, cache invalidation on update, a one-hour cache TTL, and no configured rate limit.

The gateway is intended to route hosted model calls used by ingestion and later query flows.

After the script creates the gateway, finish the AI Gateway setup in the Cloudflare dashboard:

1. Open the Cloudflare dashboard and select the same account as `CLOUDFLARE_ACCOUNT_ID`.
2. Go to AI -> AI Gateway.
3. Open the `kirana-ai-gateway` gateway.
4. Go to the gateway settings page.
5. Select Create authentication token. Use a token with the required AI Gateway `Run` permission.
6. Copy the token immediately; Cloudflare will not show it again.
7. Add it to `backend/.env` as `CLOUDFLARE_AI_GATEWAY_API_TOKEN`.
8. Toggle on Authenticated Gateway.

When Authenticated Gateway is enabled, requests must include:

```http
cf-aig-authorization: Bearer <CLOUDFLARE_AI_GATEWAY_API_TOKEN>
```

This project uses bring-your-own-key (BYOK) provider keys through AI Gateway. Configure the upstream model provider keys in the same gateway:

1. In Cloudflare, go to AI -> AI Gateway -> `kirana-ai-gateway`.
2. Open Provider Keys.
3. Select Add API Key.
4. Add keys for these providers:
   - Google AI Studio
   - Groq
   - Mistral AI
   - OpenRouter
5. Keep the key alias as `default` unless the code explicitly sends a `cf-aig-byok-alias` header.
6. Save each provider key and confirm it appears as active in the Provider Keys list.

Get the provider API keys from each provider console:

- Google AI Studio: create a Gemini API key in Google AI Studio.
- Groq: create an API key in the Groq console.
- Mistral AI: create an API key in La Plateforme / Mistral console.
- OpenRouter: create an API key in the OpenRouter account settings.

Provider keys are stored in Cloudflare's AI Gateway/Secrets Store configuration. They should not be copied into this repository's `.env`; the app authenticates to the gateway with `CLOUDFLARE_AI_GATEWAY_API_TOKEN`, and the gateway attaches the correct upstream provider key at request time.

### Tigris Object Store

Creates the `kirana-kb-raw-data` bucket through Tigris' S3-compatible API:

- S3 endpoint: `https://t3.storage.dev`
- IAM endpoint in config: `https://iam.storage.dev`
- region: `auto`

The bucket stores raw receipt images. D1 stores the resulting object URL on the corresponding receipt row after ingestion.
