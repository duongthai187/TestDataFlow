# Monitoring & Incident Management

- `chien-luoc-observability.md`: kiến trúc thu thập metric, log, alert cho toàn bộ stack dữ liệu (Prometheus, Grafana, Loki, Alertmanager, exporters).
- `incident-runbook.md`: quy trình xử lý sự cố chuẩn, kịch bản phổ biến và checklist hậu kiểm.
- `case-kafka-lag.md`: ví dụ sử dụng hệ thống observability để xử lý cảnh báo consumer lag cao.

## Khởi động stack observability
- `docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d` để bật toàn bộ dịch vụ kèm exporters.
- Truy cập Grafana tại http://localhost:3000 (admin/admin12345), Prometheus tại http://localhost:9090.
- Prometheus hiện thu thập metric từ Flink (9249/9250), Kafka (9308), Spark master/worker, Cassandra (9500-9502), MySQL (9104), PostgreSQL (9187), MinIO (9000), Doris (8030), Kafka Connect (9404), Trino (9405) cùng các HTTP probe (blackbox exporter) kiểm tra MinIO, Nessie, Doris, Trino, Connect, Spark, Flink.
- Tất cả microservice HTTP nay đều có endpoint `/health`; `docker compose ps --format "table {{.Name}}\t{{.State}}\t{{.Health}}"` giúp theo dõi trạng thái. Compose đã cấu hình `depends_on.condition: service_healthy` nên container downstream chỉ khởi động khi dependency ở trạng thái `healthy`, giảm lỗi race sau khi restart.
- Grafana dashboard `Dataflow Overview` đã bổ sung panel cho Cassandra/Paimon (qua Flink job), MySQL, PostgreSQL, Kafka Connect, Trino, MinIO, tình trạng HTTP probe, nhóm panel "Notification" (send rate, rate limited, drops, opt-outs, rate limiter errors) và các panel "Support timeline p95 latency", "Support attachment backlog", "Support timeline cache events", "Support timeline failure stages" để hỗ trợ vận hành end-to-end.
- Prometheus rule group `dataflow-runtime`/`support-service` bổ sung các alert `NotificationFailureRateHigh`, `NotificationRateLimitedBurst`, `NotificationOptOutSpike`, `NotificationRateLimiterErrors`, `SupportTimelineLatencyHigh`, `SupportTimelineCollectionFailures`, `SupportTimelineCacheErrors`, `SupportAttachmentBacklogHigh`, `SupportAttachmentGrowthRapid` giúp SRE phản ứng sớm với sự cố dịch vụ Notification/Support.
- Synthetic monitoring: script `scripts/synthetic/support_timeline_probe.py` tạo ticket kiểm thử, đo độ trễ timeline và trả JSON report. Có thể chạy cục bộ bằng `make support-probe ARGS="--base-url http://support:8000"` hoặc thông qua workflow GitHub Actions định kỳ `Support Synthetic Probe` (cron 02:00 UTC) để phát hiện sớm vấn đề timeline.
- Bảo trì định kỳ: script `scripts/maintenance/offload_support_attachments.py` hỗ trợ offload file đính kèm quá hạn sang thư mục archive/cold storage, đồng thời cập nhật metric backlog. Dùng `make support-offload ARGS="--dry-run"` để audit hoặc `--age-days <n>` khi thực sự di chuyển; workflow `Support Synthetic Probe` cũng chạy `--dry-run` mỗi đêm để đảm bảo script luôn hoạt động.

Sử dụng chung với tài liệu use case để xác định phạm vi ảnh hưởng và hành động phù hợp khi xảy ra sự cố.
