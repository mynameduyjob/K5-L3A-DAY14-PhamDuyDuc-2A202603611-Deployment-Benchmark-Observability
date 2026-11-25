import os
import random
from locust import HttpUser, between, task

QUESTIONS = [
    "Docker container giải quyết vấn đề gì khi deploy?",
    "Multi-stage build trong Dockerfile có lợi ích gì?",
    "Readiness probe khác gì liveness probe?",
    "Graceful shutdown xử lý SIGTERM như thế nào?",
    "Vì sao SLO latency nên dùng p95 thay vì trung bình?",
    "Prometheus thu thập metrics theo cơ chế push hay pull?",
    "Trong distributed tracing, span là gì?",
    "JWT khác gì API key trong xác thực?",
    "Kubernetes HPA scale dựa trên những chỉ số nào?",
    "Chi phí gọi LLM được tính dựa trên những gì?",
]


class AgentUser(HttpUser):
    wait_time = between(0.3, 1.0)

    def on_start(self):
        self.api_key = os.getenv("AGENT_API_KEY", "day14-lab-key")
        self.headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    @task(9)
    def ask_agent(self):
        self.client.post(
            "/ask",
            json={"question": random.choice(QUESTIONS)},
            headers=self.headers,
            name="/ask",
        )

    @task(1)
    def health_check(self):
        self.client.get("/health", name="/health")
