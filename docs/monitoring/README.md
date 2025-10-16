# Monitoring & Incident Management

- `chien-luoc-observability.md`: kiến trúc thu thập metric, log, alert cho toàn bộ stack dữ liệu (Prometheus, Grafana, Loki, Alertmanager, exporters).
- `incident-runbook.md`: quy trình xử lý sự cố chuẩn, kịch bản phổ biến và checklist hậu kiểm.
- `case-kafka-lag.md`: ví dụ sử dụng hệ thống observability để xử lý cảnh báo consumer lag cao.

## Khởi động stack observability
- `docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d` để bật toàn bộ dịch vụ kèm exporters.
- Truy cập Grafana tại http://localhost:3000 (admin/admin12345), Prometheus tại http://localhost:9090.
- Prometheus hiện thu thập metric từ Flink (9249/9250), Kafka (9308), Spark master/worker, Cassandra (9500-9502), MySQL (9104), PostgreSQL (9187), MinIO (9000), Doris (8030), Kafka Connect (9404), Trino (9405) cùng các HTTP probe (blackbox exporter) kiểm tra MinIO, Nessie, Doris, Trino, Connect, Spark, Flink.
- Grafana dashboard `Dataflow Overview` đã bổ sung panel cho Cassandra/Paimon (qua Flink job), MySQL, PostgreSQL, Kafka Connect, Trino, MinIO và tình trạng HTTP probe để hỗ trợ vận hành end-to-end.

Sử dụng chung với tài liệu use case để xác định phạm vi ảnh hưởng và hành động phù hợp khi xảy ra sự cố.
