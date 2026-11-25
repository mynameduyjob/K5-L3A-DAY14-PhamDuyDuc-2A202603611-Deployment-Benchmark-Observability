# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được ghi nhận trực tiếp từ các file JSON trong `reports/` do `load_test.py` và `eval/run_eval.py` xuất ra.

**Họ tên:** Phạm Duy Đức  
**Ngày chạy:** 2026-11-25  
**Môi trường:** Windows 11, Python 3.12.0 (`.venv`), Docker Desktop 29.9.3  

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | `< 500 ms` | Với câu hỏi chat thông thường, 95% người dùng cần nhận phản hồi dưới nửa giây để trải nghiệm mượt; phù hợp với ngưỡng mặc định của `load_test.py`. |
| Error rate `/ask` | `< 2.0 %` | Cho phép error budget 2% để chịu được lỗi upstream ngẫu nhiên của mock LLM (`MOCK_ERROR_RATE=0.01`) ở mức tải bình thường mà không báo động giả. |
| Accuracy trên golden dataset | `≥ 85 %` (mục tiêu sau sửa KB: `100 %`) | Đảm bảo agent trả lời đúng kiến thức cốt lõi trước khi merge/deploy và chặn regression so với phiên bản trước. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, `MOCK_SLOW_RATE=0.03`, 300 requests/mức)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.04 | 211.6 | 303.2 | 1721.4 | 1.00% | PASS |
| 10 | 36.98 | 198.3 | 236.0 | 1715.0 | 1.33% | PASS |
| 50 | 94.08 | 229.4 | 665.4 | 1769.4 | 2.33% | FAIL |
| 100 | 42.57 | 912.9 | 4526.2 | 5268.6 | 1.33% | FAIL |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

Không. Từ `c=1` lên `c=10` và `c=50`, RPS tăng mạnh (`4.04 → 36.98 → 94.08 req/s`) nhờ xử lý bất đồng bộ (`async/await`). Tuy nhiên lên tới `c=100`, hệ thống 1 process bị bão hòa (event loop scheduling overhead + giới hạn tài nguyên xử lý đồng thời), khiến RPS **giảm ngược** xuống `42.57 req/s` và `p50` nhảy từ `229.4 ms` lên `912.9 ms`, `p95` vọt lên `4526.2 ms` (ở `c=50` cũng bắt đầu vượt SLO cả `p95=665.4 ms` lẫn `error_rate=2.33%`).

### 2.2 Tail latency (`--requests 300 --concurrency 20`, agent v2)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 205.7 | 249.7 | 268.7 |
| 0.03 (mặc định) | 239.6 | 257.3 | 1714.2 |
| 0.1 | 324.6 | 1677.5 | 1713.5 |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

`p99` và `p95` nhạy hơn rất nhiều so với `avg`:
- Khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03` (3% request bị chậm), `avg` chỉ tăng nhẹ `33.9 ms` (`205.7 → 239.6 ms`, trông vẫn rất ổn), nhưng `p99` nhảy vọt hơn 6 lần từ `268.7 ms` lên `1714.2 ms`.
- Khi `MOCK_SLOW_RATE = 0.1` (>5% request chậm), cả `p95` cũng vọt lên `1677.5 ms` trong khi `avg` mới là `324.6 ms`.
Vì average bị kéo xuống bởi 90–97% request nhanh nên **che giấu trải nghiệm tệ của nhóm người dùng gặp tail latency**; SLO phải đặt theo `p95`/`p99`.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 (`eval_v1.json`) | Agent v2 (`eval_v2.json`) | Agent v2 sau sửa KB (`eval_v2_fixed.json`) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.2 | 108.8 | 113.7 |
| Tổng cost (USD) | $0.000406 | $0.000758 | $0.000790 |
| Cost / câu đúng (USD) | $0.00040575 | $0.00003607 | $0.00003436 |
| Quality gate | FAIL | PASS (`≥ 80%`) | PASS (`≥ 100%`, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Cách đã sửa |
| --- | --- | --- |
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry `(["jwt"], "API key là chuỗi bí mật cố định, không tự hết hạn. JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn; server xác minh chữ ký mà không cần tra database.")` vào `KNOWLEDGE_BASE` trong `utils/mock_llm.py`. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry `(["hpa", "kubernetes", "autoscal"], "Kubernetes HPA (Horizontal Pod Autoscaler) scale số pod dựa trên CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi.")` vào `KNOWLEDGE_BASE` trong `utils/mock_llm.py`. |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Chất lượng:** v2 (có bước retrieval) nâng accuracy từ `4.3%` lên `91.3%` (và `100%` sau khi bổ sung knowledge base), cải thiện 20 câu và không gây regression.
- **Chi phí:** Do prompt của v2 có thêm context được retrieve nên `avg_tokens` tăng gần gấp đôi (`57.2 → 108.8–113.7 tokens/câu`) và tổng chi phí tăng từ `$0.000406` lên `$0.000790`. Tuy nhiên xét hiệu quả thực tế, **`cost / câu đúng` của v2 (`$0.00003436`) rẻ hơn gần 12 lần so với v1 (`$0.00040575`)**.
- **Latency:** v2 chậm hơn một chút ở mức trung vị (`p50: 168.2 ms → 190.2–203.0 ms`, `p95: 197.9 ms → 220.9–234.6 ms`) do thêm bước `search_knowledge_base` (~20ms) và input prompt dài hơn, nhưng hoàn toàn nằm trong SLO `< 500 ms`.
- **Quality gate CI:** File `.github/workflows/eval.yml` chạy `eval/run_eval.py --min-accuracy 0.85`; khi accuracy dưới ngưỡng hoặc có câu regression so với baseline, script trả về **exit code `1`**, khiến job CI fail và chặn merge PR.

---

## 4. Observability stack (production)

> Đã chạy full stack Docker Compose (`agent` x2 + `nginx` + `prometheus` + `grafana` + `jaeger` + `locust`) với `-p k5-day14-observability`; `promtool test rules /p/alert_rules_test.yml` đạt **`SUCCESS`**.
> - **Exercise 7.4 (Prometheus / Grafana khi có tải 2 instance):** `p95 = 299.3 ms` vs `avg = 248.0 ms` (khoảng cách ~51 ms phản ánh nhóm ~3% request slow tail); Nginx chia tải tương đối đều giữa 2 instance (`17.67 req/s` và `14.55 req/s`); `input tokens/s = 2441.4` lớn hơn `output tokens/s = 1251.6` (~2x) vì prompt của v2 có thêm system prompt + tài liệu retrieve; `GET http://localhost:8080/metrics` trả **HTTP 404** vì Nginx chặn route `/metrics` không public ra ngoài.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (`screenshots/grafana-dashboard.png`)
- [x] Một trace chậm trong Jaeger (`screenshots/jaeger-slow-trace.png`)
- [x] Một trace lỗi trong Jaeger (`screenshots/jaeger-error-trace.png`)
- [x] Trang Alerts của Prometheus với ≥ 2 alert đang **firing** (`screenshots/prometheus-alert-firing.png`)

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | `99.2s` | Error Rate (%) & Requests/s theo status (`503`) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | `150.5s` | p95 Latency & Latency p50/p95/p99/avg |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | `119.8s` | Cost Rate ($/hour) & Cost USD/giờ |
| D | `docker pause` 1 instance | `AgentInstanceDown` | ~`30–40s` (`for: 30s`, chưa chạy riêng ở đợt này) | Instances Up & Requests/s theo instance |
| E | `AGENT_VERSION=v1` | Không có | N/A | Retrieval hit ratio mất / Tokens/s giảm / Bảng `agent_info` |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Các alert hạ tầng (error rate, latency, CPU/RAM, instance down) chỉ đo sức khỏe kỹ thuật của hệ thống, không đo độ chính xác câu trả lời. Để phát hiện giảm chất lượng như thí nghiệm E, cần chạy **eval định kỳ trên golden dataset** trong CI/CD trước khi deploy (quality gate), kết hợp theo dõi metric nghiệp vụ/chất lượng như `agent_retrieval_total{result="miss"}`, tỷ lệ hit retrieval và feedback/LLM-as-judge trên mẫu traffic production.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất tìm được trong Jaeger / log JSON:

- `trace_id`: `801784f37e78b4b21bc86bef513dad9a` (ngoài ra trace lỗi mẫu: `trace_id = 1a4926d9578d9d3e7fc25383ee958332`, event `llm_error`)
- Tổng thời gian: `1721.5` ms (`POST /ask`)
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (`1696.2` ms, `98.5%`; `agent.retrieve_context` chỉ mất `22.5` ms = `1.3%`)
- Dòng log tương ứng (khớp `trace_id`):

```json
{"ts": "2026-11-25T15:26:27.290589+00:00", "level": "INFO", "service": "observable-agent", "instance": "0f71c970cb3a", "event": "llm_call", "trace_id": "801784f37e78b4b21bc86bef513dad9a", "span_id": "3282fd793c45e564", "request_id": "2af678bc9ed1", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1696.3}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu `Aggregated` trích trực tiếp từ `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`:

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | `82.93` (`74.61` cho `/ask`) | `230` | `1800` (`1900` cho `/ask`) | `2800` (`2900` cho `/ask`) | `108 / 9850` (`1.10%`) |
| 3 | `106.36` (`95.94` cho `/ask`) | `200` | `600` (`660` cho `/ask`) | `1700` | `128 / 12648` (`1.01%`) |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

Scale từ 1 lên 3 instance giúp **cải thiện rất mạnh `p95` (từ `1800 ms` giảm còn `600 ms`, tức giảm 3 lần)** và tăng tổng throughput từ `82.93` lên `106.36 req/s`: khi chỉ có 1 container bị giới hạn `0.5 CPU`, 100 user đồng thời tạo hàng đợi trên 1 worker nên p95 bị đội lên gần 2 giây; chia tải qua 3 instance giúp giảm hẳn thời gian chờ hàng đợi. Tuy nhiên `p99` dừng ở `1700 ms` và `p50` giảm nhẹ từ `230 ms` xuống `200 ms`, bởi nút thắt cơ bản vẫn nằm ở **độ trễ gọi LLM (`chat mock-llm-small`, ~150ms bình thường và ~1700ms với 3% slow tail)** — việc thêm instance chỉ giải quyết nghẽn CPU/concurrency chứ không làm mỗi lần gọi LLM nhanh hơn.

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. `average` che giấu tail latency: cần đặt SLO theo `p95`/`p99` để phản ánh đúng trải nghiệm của nhóm người dùng chậm nhất.
  2. Eval trên golden dataset kèm quality gate trong CI và chỉ số `cost / câu đúng` giúp đánh giá đúng giá trị của RAG (v2 tốn gần gấp đôi token nhưng `cost / câu đúng` rẻ hơn ~12 lần v1) và chặn regression trước khi lên production.
  3. Cần kết hợp cả 3 trụ cột Metrics (Prometheus/Grafana), Traces (OpenTelemetry/Jaeger) và Structured JSON Logs gắn `trace_id` để đi từ cảnh báo tổng quan tới đúng bước gây chậm/lỗi.
- Nếu đưa agent này lên production thật, sẽ thêm metric/alert nào nữa:
  - Alert cho **retrieval miss rate tăng cao** (`rate(agent_retrieval_total{result="miss"}[5m])`) để phát hiện sớm suy giảm chất lượng RAG/knowledge base.
  - Giám sát **HTTP 5xx/504 ở tầng Nginx/Ingress** (blackbox/synthetic probe từ bên ngoài) vì lỗi timeout tại load balancer không được metric bên trong app ghi nhận.
  - Theo dõi **Redis latency / rate limit 429 rate / budget 402 rate** để phát hiện sớm tấn công lạm dụng hoặc user sắp chạm ngưỡng chi phí.
