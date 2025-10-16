# Chiến lược monitoring & xử lý sự cố

## 1. Mục tiêu
- Bảo đảm các SLO: latency realtime < 2 phút, độ trễ batch < 30 phút, Kafka backlog < 5.000 message/partition, job Flink uptime > 99%.
- Cảnh báo sớm các sự cố (lag, node down, lỗi schema) và cung cấp quy trình phản ứng chuẩn.
- Ghi nhận lịch sử sự kiện, log và metric để phục vụ phân tích nguyên nhân gốc (RCA).

## 2. Kiến trúc quan sát đề xuất
```
Prometheus (thu metric) ← exporters (Kafka, Flink, Spark, Cassandra, MySQL, PostgreSQL, Trino, Kafka Connect, MinIO, Doris, blackbox)
Grafana (dashboard tổng quan + drill-down)
Alertmanager (cảnh báo) → Teams/Slack/Email (tích hợp sau)
Loki + Promtail (log aggregation) → Grafana Explore
Tempo (tuỳ chọn) để truy vết job khi bổ sung OpenTelemetry
```
- **Triển khai**: `docker-compose.monitoring.yml` bao gồm Prometheus, Grafana, Alertmanager, Loki, Promtail, cAdvisor, Kafka exporter, JMX exporter cho Cassandra/Trino/Kafka Connect, mysqld-exporter, postgres-exporter, MinIO metrics và blackbox exporter. Khởi chạy toàn bộ stack bằng `docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d`.
- **Kết nối metric**:
  - Kafka: bật `JMX_PORT=9999`, Prometheus đọc qua `kafka-exporter:9308`.
  - Flink: `metrics.reporters.prom.class=org.apache.flink.metrics.prometheus.PrometheusReporter` (cổng 9249/9250).
  - Spark: servlet Prometheus `/metrics/prometheus` được mount từ `monitoring/spark/metrics.properties`.
  - Cassandra: 3 sidecar JMX exporter (9500-9502) với `LOCAL_JMX=no`.
  - MySQL/PostgreSQL: `prom/mysqld-exporter` (9104) và `postgres_exporter` (9187).
  - Trino & Kafka Connect: exporter `prom/jmx-exporter` lần lượt trên 9405 và 9404.
  - Doris: scrape `/metrics` (8030); MinIO: `/minio/v2/metrics/cluster` (9000).
  - Paimon/Nessie: quan sát qua metric job Flink và HTTP probe (blackbox exporter) `http://nessie:19120/q/health/ready`.
  - Docker host: `cAdvisor` theo dõi tài nguyên container.

## 3. Dashboard & chỉ số trọng yếu
- **Kafka**: `kafka_server_broker_topic_metrics_messages_in_total`, `kafka_consumer_fetch_manager_metrics_records_lag_max`.
- **Flink**: từ REST API (port 8081) và Prometheus `flink_taskmanager_Status_JVM_CPU_Load`, `flink_jobmanager_job_latency`.
- **Cassandra**: `org_apache_cassandra_metrics_clientrequest_latency`, `pending_tasks`.
- **Spark**: servlet Prometheus `/metrics/prometheus`, chỉ số `up{job="spark-master"}`, `spark_worker_*`.
- **Paimon/Nessie**: theo dõi log commit (Loki query `service="flink-jobmanager"`) và `probe_success{instance="http://nessie:19120/q/health/ready"}`.
- **MinIO**: `minio_cluster_capacity_free_bytes`, `minio_cluster_capacity_total_bytes`, HTTP probe thành công.
- **Kafka Connect**: `kafka_connect_worker_connector_count`, `kafka_connect_worker_task_count`, `kafka_connect_connector_failed_task_count`.
- **Trino**: `trino_execution_queuedqueries`, `trino_memory_FreeBytes`, `trino_execution_RunningQueries`.

## 4. Alerting
Ví dụ cấu hình PrometheusRule:
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: dataflow-alerts
spec:
  groups:
  - name: flink
    rules:
    - alert: FlinkJobRestarting
      expr: increase(flink_jobmanager_job_numRestarts[5m]) > 0
      for: 2m
      labels:
        severity: critical
      annotations:
        summary: "Job Flink restart liên tục"
        description: "Kiểm tra checkpoint và log job {{ $labels.job_name }}"
  - name: kafka
    rules:
    - alert: KafkaLagHigh
      expr: kafka_consumer_fetch_manager_metrics_records_lag_max > 5000
      for: 5m
      labels:
        severity: warning
```
Alertmanager gửi thông báo qua webhook/Email. Đối với sự cố nghiêm trọng, kích hoạt quy trình on-call.

## 5. Log & trace
- **Loki + Promtail**: mount `/var/lib/docker/containers` và label theo service. Dễ dàng truy vấn `container="flink-jobmanager"` để xem stacktrace.
- **Structured logging**: cấu hình Flink sử dụng JSON log (`log4j2.component.properties`). Debezium Connect hỗ trợ log JSON qua env `CONFIG_LOG4J_LEVEL`.
- **Trace**: Khi bổ sung OpenTelemetry, xuất span từ ứng dụng microservice vào Tempo/Jaeger để liên kết sự kiện upstream.

## 6. Quy trình phản ứng sự cố
1. **Phát hiện**: Alertmanager bắn cảnh báo.
2. **Đánh giá**: kiểm tra dashboard Grafana tương ứng (Flink, Kafka, Cassandra).
3. **Hành động sơ cấp**:
   - Lag Kafka cao: kiểm tra consumer Flink, tăng parallelism (`docker compose scale flink-taskmanager=2`).
   - Flink job fail: xem log qua Grafana/Loki, khôi phục từ checkpoint mới nhất (`Flink UI → Restore`).
   - Cassandra node down: `docker compose logs cassandra-nodeX`, chạy `nodetool status`; nếu lỗi disk, chuyển traffic sang node khác.
4. **Ghi nhận**: mở ticket trong hệ thống ITSM, note timestamp, metric, nguyên nhân tạm thời.
5. **Phục hồi**: sau khi khắc phục, xác thực data quality bằng cách chạy truy vấn đối chiếu trên Trino/Doris.
6. **RCA & cải tiến**: cập nhật tài liệu runbook, bổ sung alert nếu thiếu.

## 7. Tự động hoá & phòng ngừa
- Thiết lập `Flink REST API` (8081) script kiểm tra trạng thái job mỗi 5 phút; nếu phát hiện STATE `FAILED`, tự động gọi `POST /jobs/:jobid/yarn-cancel` (hoặc `/-/resubmit`).
- Dùng `Kafka Cruise Control` (hoặc script) cân bằng partition khi phát hiện `leader imbalance`.
- Lập lịch job Spark kiểm tra tính toàn vẹn dữ liệu (ví dụ so sánh tổng tiền đơn hàng giữa MySQL và bảng `finance_fact`).
- Bảo vệ S3/MinIO bằng lifecycle rule và cảnh báo dung lượng.

## 8. Checklist triển khai
- [x] Tạo compose file monitoring, mount cấu hình Prometheus.
- [x] Bật JMX / metrics reporter cho Kafka, Spark, Flink, Cassandra, Connect, Trino, MinIO.
- [x] Khởi tạo dashboard Grafana `Dataflow Overview` (json provisioning).
- [ ] Thiết lập alert route (Email/Teams) và kiểm thử bằng `amtool`.
- [ ] Đào tạo đội ngũ vận hành đọc dashboard và xử lý runbook.

Chiến lược này kết hợp metric, log và alert giúp đội ngũ chủ động nắm bắt sức khỏe hệ thống, phù hợp với tính chất realtime của nền tảng dữ liệu.
