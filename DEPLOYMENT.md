# Deployment Information

## Public URL
https://agent-production-72cd4df6.up.railway.app

## Platform
Railway (Project: `day14-ai-agent` · Services: `agent`, `Redis`)

## Test Commands

### Health & Readiness Checks
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "https://agent-production-72cd4df6.up.railway.app/health"
# Expected: 200

curl -sS -o /dev/null -w '%{http_code}\n' "https://agent-production-72cd4df6.up.railway.app/ready"
# Expected: 200
```

### API Test (with authentication)
```bash
# Without API key (expected: 401)
curl -sS -o /dev/null -w '%{http_code}\n' \
  -X POST "https://agent-production-72cd4df6.up.railway.app/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'

# With API key (expected: 200)
curl -X POST "https://agent-production-72cd4df6.up.railway.app/ask" \
  -H "X-API-Key: YOUR_AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
```

## Environment Variables Set (on Railway Dashboard)
- `ENVIRONMENT=production`
- `REDIS_URL=${{Redis.REDIS_URL}}`
- `AGENT_API_KEY` (đặt trực tiếp trên Railway, không ghi trong mã nguồn)
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`
- `MONTHLY_BUDGET_USD=10.0`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
