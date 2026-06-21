# ASKSpark

This app now expects secrets to be provided through environment variables instead of being hardcoded in the source.

Required variables:

- `AZURE_CLIENT_SECRET`
- `DB_PASSWORD`
- `DATABRICKS_API_TOKEN`
- `ACCOUNT_API_CLIENT_SECRET`
- `SYSTEM_API_CLIENT_SECRET`
- `OUTAGE_API_CLIENT_SECRET`
- `SERVICENOW_USERNAME`
- `SERVICENOW_PASSWORD`

Optional variables with defaults:

- `FLASK_SECRET_KEY`
- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `DB_DRIVER`
- `DB_SERVER`
- `DB_NAME`
- `DB_USER`
- `DB_CONNECTION_TIMEOUT`