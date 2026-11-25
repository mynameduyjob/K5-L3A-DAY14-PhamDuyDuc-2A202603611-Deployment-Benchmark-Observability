# Day 14 Lab — Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`
1. **Hardcode secret trong mã nguồn (dòng 17–18):** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Đẩy lên Git sẽ lộ thông tin nhạy cảm ngay lập tức.
2. **Hardcode cấu hình debug/model (dòng 21–22):** `DEBUG = True`, `MAX_TOKENS = 500` không đọc từ biến môi trường nên không thể đổi giữa dev/staging/prod mà không sửa code.
3. **Dùng `print()` và log lộ secret (dòng 33–38):** `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` làm lộ API key ra stdout và không có cấu trúc JSON để hệ thống thu thập log phân tích.
4. **Không có health check / readiness endpoint (dòng 42–43):** Không có `GET /health` hay `GET /ready`, nên nền tảng cloud/load balancer không biết khi nào container chết để restart hoặc chưa sẵn sàng nhận traffic.
5. **Bind `localhost`, cố định `port=8000` và bật `reload=True` (dòng 49–53):** `host="localhost"` khiến container không nhận được kết nối từ bên ngoài, `port=8000` không nhận biến `PORT` do cloud cấp, còn `reload=True` gây tốn tài nguyên và mất ổn định trong production.
6. **Không xử lý graceful shutdown:** Không dùng `lifespan` hay xử lý `SIGTERM`, dễ cắt ngang request đang chạy khi restart/deploy.

### Exercise 1.2: Kết quả chạy bản `develop`
```bash
curl -X POST "http://localhost:8000/ask?question=Hello"
# HTTP 200:
# {"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```
Bản `production` (`01-localhost-vs-production/production/app.py`) đã tách endpoint chuẩn hơn:
- `GET /health` → `200 {"status":"ok","uptime_seconds":2.6,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T10:06:04.100346+00:00"}`
- `GET /ready` → `200 {"ready":true}`
- `POST /ask` (JSON) → `200 {"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","model":"gpt-4o-mini"}`

### Exercise 1.3: So sánh `develop` vs `production`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Tại sao quan trọng? |
| --- | --- | --- | --- |
| **Config & Secrets** | Hardcode trong file (`OPENAI_API_KEY`, `DATABASE_URL`, `port=8000`) | Đọc từ biến môi trường qua `Settings` (`os.getenv`), `validate()` fail-fast khi thiếu key ở production | Tuân thủ 12-Factor App, không lộ secret trên Git, dùng chung 1 artifact cho dev/staging/prod |
| **Network Binding** | `host="localhost"`, `port=8000`, `reload=True` | `host="0.0.0.0"`, `port=int(os.getenv("PORT", 8000))`, `reload=settings.debug` | Bắt buộc để container nhận traffic từ Docker/cloud LB và dùng đúng port do platform cấp |
| **Health & Readiness** | Không có | Có `GET /health` (liveness) và `GET /ready` (readiness, trả `503` nếu chưa sẵn sàng) | Platform biết khi nào cần restart container hỏng và khi nào mới được route traffic vào |
| **Logging** | `print(...)` text thuần, log cả API key | `logging` xuất JSON (`{"time":...,"level":...,"msg":...}`), không log secret | Dễ index, lọc, cảnh báo trên log aggregator và không làm rò rỉ thông tin nhạy cảm |
| **Shutdown** | Thoát đột ngột | Dùng `lifespan` + `signal.SIGTERM` handler | Hoàn thành request in-flight và đóng kết nối trước khi container dừng |

---

## Part 2: Docker

### Exercise 2.1: Trả lời câu hỏi về `02-docker/develop/Dockerfile`
1. **Base image:** `python:3.11` (bản đầy đủ Debian + công cụ build + Python 3.11, dung lượng lớn ~1 GB).
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Tại sao `COPY requirements.txt` đứng trước `COPY app.py`:** Docker cache từng layer. Nếu chỉ sửa source code mà không đổi `requirements.txt`, Docker tái sử dụng lại layer đã chạy `pip install`, giúp rebuild rất nhanh.
4. **`CMD` vs `ENTRYPOINT`:** `ENTRYPOINT` là lệnh cố định của container, còn `CMD` là lệnh/tham số mặc định và có thể bị ghi đè khi chạy `docker run <image> <command>`.

### Exercise 2.2 & 2.3: Build, đo kích thước và so sánh Multi-stage

Lệnh build từ gốc repo:
```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
docker images my-agent --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}"
```

Kết quả đo thực tế:
- **Develop (`my-agent:develop`):** `1.67 GB` (~`1670 MB`)
- **Production (`my-agent:advanced`):** `240 MB`
- **Mức giảm:** giảm **`1430 MB` (~`85.6%`)**

**Giải thích multi-stage:**
- **Stage 1 (`builder`):** Dùng `python:3.11-slim`, cài `gcc`, `libpq-dev` và `pip install --user -r requirements.txt` vào `/root/.local`.
- **Stage 2 (`runtime`):** Bắt đầu lại từ `python:3.11-slim` sạch, chỉ `COPY --from=builder /root/.local` (các thư viện đã cài) cùng source code, chạy bằng user non-root `appuser` và có `HEALTHCHECK`. Không mang `gcc`, header files hay apt cache vào image cuối nên nhẹ hơn rất nhiều và giảm bề mặt tấn công.

### Exercise 2.4: Docker Compose Stack (`02-docker/production/`)

Sơ đồ kiến trúc các service:
```text
Client ──▶ Nginx (:80) ──▶ Agent (:8000) ──┬──▶ Redis (:6379)
                                           └──▶ Qdrant (:6333)
```

- Tạo `.env.local` và chạy `docker compose -p k5-day14-docker up -d --build`.
- Kết quả test qua Nginx:
  - `GET http://localhost/health` → `200 {"status":"ok","uptime_seconds":0.5,"version":"2.0.0","timestamp":"2026-11-25T10:10:15.304421"}`
  - `POST http://localhost/ask` → `200 {"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}`

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy Agent Part 6 lên Cloud
- **Nền tảng chính:** Railway (deploy thư mục `06-lab-complete/` kèm template `Redis`)
- **Public URL:** https://agent-production-72cd4df6.up.railway.app
- **Railway Project:** https://railway.com/project/e0356523-8532-4a16-a31a-9e37a7151057
- **Kết quả tự kiểm CP6 (4 lệnh):**
  - `GET /health` → `200` (`{"status":"ok","environment":"production"}`)
  - `GET /ready` → `200` (`{"status":"ready"}`)
  - `POST /ask` (không có `X-API-Key`) → `401`
  - `POST /ask` (có `X-API-Key`) → `200`
- **Ảnh chụp màn hình:** xem `DEPLOYMENT.md` và `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`.

### So sánh `railway.toml` và `render.yaml`

| Tiêu chí | `railway.toml` | `render.yaml` |
| --- | --- | --- |
| **Định dạng & phạm vi** | TOML, cấu hình cho **1 service** hiện tại | YAML (Blueprint IaC), có thể khai báo **nhiều service** (web + managed Redis) trong cùng 1 file |
| **Build config** | `[build] builder = "DOCKERFILE"`, `dockerfilePath = "Dockerfile"` | `runtime: docker` (hoặc `runtime: python` kèm `buildCommand` + `startCommand`) |
| **Health check & restart** | `[deploy] healthcheckPath = "/health"`, `healthcheckTimeout`, `restartPolicyType`, `restartPolicyMaxRetries` | `healthCheckPath: /health`, `autoDeploy: true`, `region`, `plan` |
| **Quản lý biến môi trường / secrets** | Đặt qua Railway CLI (`railway variables set`) hoặc Dashboard, không khai báo secret trong file | Khai báo trực tiếp `envVars` trong file; secret dùng `generateValue: true` (tự sinh) hoặc `sync: false` (nhập tay trên dashboard) |

### Exercise 3.3: Mô tả pipeline CI/CD Cloud Run (`cloudbuild.yaml` + `service.yaml`)
Pipeline trong `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` chạy qua 4 bước tuần tự khi push lên `main`:
1. **`test`:** Dùng container `python:3.11-slim` cài `requirements.txt` + `pytest` và chạy unit test (`pytest tests/`).
2. **`build`:** Build Docker image gắn cả tag `$COMMIT_SHA` và `latest` (tận dụng `--cache-from` từ `latest`).
3. **`push`:** Đẩy image đã tag lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy`:** Gọi `gcloud run deploy` cập nhật service `ai-agent` tại region `asia-southeast1`, cấu hình `min-instances=1`, `max-instances=10`, `512Mi` RAM và nạp secret từ Google Secret Manager; kết hợp với `service.yaml` (Knative Service) định nghĩa thêm `containerConcurrency: 80`, `livenessProbe` (`/health`) và `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/`)
- **Kiểm tra ở đâu:** Hàm dependency `verify_api_key` đọc header `X-API-Key` bằng `APIKeyHeader(name="X-API-Key", auto_error=False)` và gắn vào route `/ask` qua `Depends(verify_api_key)`.
- **Sai/thiếu key:** Thiếu key trả `401`, sai key trả `403` (ở bản `06-lab-complete/` hợp nhất trả `401` cho cả thiếu và sai).
- **Rotate key:** Đọc `AGENT_API_KEY` từ biến môi trường; khi rotate chỉ cần cập nhật env trên platform/secret manager (hoặc hỗ trợ danh sách key cũ + mới trong giai đoạn chuyển tiếp) rồi restart/rolling deploy.

Kết quả test thực tế:
```text
No key  -> HTTP 401 {"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
With key -> HTTP 200 {"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2 & 4.3: JWT & Rate Limiting (`04-api-gateway/production/`)
- **Thuật toán Rate Limiter (`rate_limiter.py`):** Sliding Window Counter dùng `deque` lưu timestamp các request trong 60 giây gần nhất (`window_seconds = 60`), loại bỏ các timestamp cũ hơn `now - 60`.
- **Giới hạn & phân quyền:** `student` (role `user`) bị giới hạn **10 requests/phút** (`rate_limiter_user`), `teacher` (role `admin`) là **100 requests/phút** (`rate_limiter_admin`). Khi vượt ngưỡng trả `HTTP 429` kèm các header `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`.

Kết quả test thực tế với `POST /auth/token` (`student` / `demo123`, token đã che):
```text
POST /auth/token -> HTTP 200 (access_token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<REDACTED>)
No token         -> HTTP 401 {"detail":"Authentication required. Include: Authorization: Bearer <token>"}
Req  1 .. Req 10 -> HTTP 200 (requests_remaining giảm dần từ 9 về 0)
Req 11           -> HTTP 429 {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":57}}
Req 12           -> HTTP 429 {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":56}}
```

### Exercise 4.4: Cách làm Cost Guard với Redis
- **Tại sao cần cả Rate Limit và Cost Guard:** Rate limit bảo vệ **tốc độ gọi** (chống spam/DDoS, tránh nghẽn hệ thống), còn Cost Guard bảo vệ **tiền** (một user gọi chậm trong rate limit nhưng gửi prompt cực dài hoặc dùng model đắt vẫn có thể làm cạn ngân sách).
- **Triển khai với Redis:**
  - Dùng key theo ngày hoặc tháng, ví dụ `cost:daily:{YYYY-MM-DD}` hoặc `budget:{user_id}:{YYYY-MM}`.
  - Trước khi gọi LLM (`check_budget`): đọc tổng chi phí hiện tại từ Redis; nếu `>= budget` thì chặn ngay bằng `HTTP 402 Payment Required`.
  - Sau khi gọi LLM (`record_cost`): tính chi phí theo số token (`input_tokens * price_in + output_tokens * price_out`), cộng dồn nguyên tử bằng `INCRBYFLOAT` và đặt `EXPIRE` để tự reset sau chu kỳ.

---

## Part 5: Scaling & Reliability

### Exercise 5.1–5.3: Concepts cốt lõi
- **`/health` (liveness) vs `/ready` (readiness):** `/health` kiểm tra process còn sống hay bị treo (luôn trả `200` kể cả khi Redis tạm mất kết nối để tránh orchestrator restart hàng loạt vô ích); `/ready` kiểm tra các dependency bắt buộc (ping Redis) — nếu lỗi trả `503` để load balancer ngừng route traffic tới instance đó.
- **Graceful shutdown (`SIGTERM`):** Khi orchestrator dừng/deploy container, nó gửi `SIGTERM`. Ứng dụng phải ngừng nhận kết nối mới, hoàn thành các request đang xử lý (in-flight), đóng kết nối Redis/DB cleanly rồi thoát với exit code `0` trước khi hết grace period (tránh bị `SIGKILL` / exit 137).
- **Stateless design:** Lưu rate limit, budget, session/history trong **Redis** dùng chung thay vì dict/deque trong RAM. Nếu lưu trong RAM, khi scale nhiều worker hoặc nhiều container sau load balancer, mỗi instance thấy một state khác nhau và mất sạch dữ liệu khi restart.

### Exercise 5.4 & 5.5: Test Stateless với Nginx + 3 Agent Instances + Redis
Chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` trong `05-scaling-reliability/production/`, sau đó chạy `python test_stateless.py`:

```text
Session ID: dd3d8a80-8b5e-4ca7-89c0-74f089c258b8

Request 1: [instance-e5aec2]  Q: What is Docker?
Request 2: [instance-245639]  Q: Why do we need containers?
Request 3: [instance-e5aec2]  Q: What is Kubernetes?
Request 4: [instance-50e35e]  Q: How does load balancing work?
Request 5: [instance-245639]  Q: What is Redis used for?

Total requests: 5
Instances used: {'instance-245639', 'instance-50e35e', 'instance-e5aec2'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```
Các request được Nginx phân tán round-robin qua 3 container khác nhau (`instance-e5aec2`, `instance-245639`, `instance-50e35e`), nhưng toàn bộ 10 message của phiên hội thoại vẫn được lưu và truy xuất đầy đủ nhờ lưu state tập trung trên Redis.

---

## Part 6: Final Project (`06-lab-complete/`)

Kết quả chạy `python check_production_ready.py --public-url https://agent-production-72cd4df6.up.railway.app` trong `06-lab-complete/` trên WSL2 Ubuntu (Python 3.11.18, Docker Desktop 29.9.3; image multi-stage **238 MB**, `docker stop` exit code `0` trong `0.7s`):

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 44/44 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

---

## AI log

1. **Hỏi gì:** Nhờ AI rà soát các TODO trong `06-lab-complete/`, chạy eval Part 7 và đối chiếu kết quả.
2. **Nhận gì:**
   - Phát hiện thiếu các bản sao `utils/mock_llm.py` và thiếu thư mục cấu hình `nginx/`, `prometheus/`, `grafana/`, `locust/` trong `benchmark-observability/production/`.
   - Được đề xuất cấu trúc triển khai các tiêu chí trong `lifespan` trong `main.py`, multi-stage `Dockerfile`, `docker-compose.yml` và bổ sung metric `agent_question_length_chars`.
3. **Tự sửa & tự kiểm tra thế nào:**
   - Tự kiểm tra từng module trong `06-lab-complete/` để đảm bảo không hardcode secret, không ping Redis khi import, và chạy `check_production_ready.py` trên WSL2 Ubuntu với Docker Desktop đạt **`PASS 12/12` (`44/44 checks passed`)**, image `238 MB`, `docker stop` `0.7s`.
   - Tự chạy `01-localhost-vs-production`, `02-docker` (`1.67 GB` vs `240 MB`), `04-api-gateway` (`401`/`200`/`429`), `05-scaling-reliability` (`--scale agent=3` + `test_stateless.py`), và toàn bộ script `load_test.py` + `eval/run_eval.py` cho Part 7; toàn bộ số liệu trong `MISSION_ANSWERS.md` và `BENCHMARK_REPORT.md` đều đối chiếu trực tiếp với output lệnh và các file JSON trong `reports/`.
