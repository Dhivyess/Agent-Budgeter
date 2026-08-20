#!/bin/bash

if [ -z "$LITELLM_MASTER_KEY" ]; then
  echo "Error: LITELLM_MASTER_KEY environment variable is not set."
  exit 1
fi

# Provision Team Budget ($500/month)
echo "Creating Engineering Team..."
curl -X POST 'http://localhost:4000/team/new' \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "team_alias": "engineering",
    "max_budget": 500.0,
    "budget_duration": "30d"
  }'

echo -e "\n\nGenerating Agent Virtual Key..."
# Provision Agent Key ($50/month with Model Fallback)
# Replace <ENGINEERING_TEAM_ID> with the actual team_id returned from the previous call
curl -X POST 'http://localhost:4000/key/generate' \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "team_id": "37c9a0cf-9832-486f-af0e-b357daf2f9ed",
    "key_alias": "agent-code-reviewer",
    "max_budget": 50.0,
    "budget_duration": "30d"
  }'
