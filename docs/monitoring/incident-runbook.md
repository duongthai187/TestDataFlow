# Incident Runbook

## 1. Phạm vi
Áp dụng cho toàn bộ stack realtime-lakehouse (Kafka, Debezium, Flink, Paimon, Cassandra, Spark, Doris, Trino, MinIO, Nessie). Kết hợp với chiến lược observability trong `chien-luoc-observability.md`.

## 2. Quy tắc chung
- Luôn kiểm tra bảng trạng thái `docs/usecases` để xác định pipeline chịu ảnh hưởng.
- Ghi nhận sự cố trong hệ thống ITSM: timestamp, dịch vụ, metric vi phạm, commit hash Nessie liên quan.
- Sau mỗi sự cố phải cập nhật mục "Lesson Learned".

## 3. Quy trình 5 bước
1. **Phát hiện**
   - Alert Prometheus/Alertmanager, log anomalies qua Grafana Loki.
   - Agent CS hoặc user báo lỗi -> tạo ticket.
2. **Chuẩn đoán**
   - Kiểm tra `docker compose ps`, xác nhận container.
   - Xem Grafana dashboard `Dataflow Overview` (panel Service availability, Cassandra latency, MySQL/PostgreSQL connection, Kafka Connect, Trino, MinIO, HTTP probe).
   - Dùng Flink REST API (8081) lấy trạng thái job (`/jobs/:jobid`).
   - Dùng `nodetool status` cho Cassandra, `bin/kafka-topics.sh --describe` cho Kafka, `minio client admin info` khi cần.
3. **Khắc phục tạm thời**
   - Khôi phục job Flink từ checkpoint (`POST /jobs/:jobid/rescale` hoặc UI).
   - Scale thêm TaskManager (`docker compose up -d --scale flink-taskmanager=2`).
   - Chuyển traffic sang branch Paimon ổn định (Nessie `merge --from backup`).
4. **Phục hồi hoàn toàn**
   - Kiểm tra tính toàn vẹn dữ liệu (Spark/Trino query).
   - Xác nhận alert đã clear, metric trở lại ngưỡng.
   - Cập nhật stakeholder.
5. **Hậu kiểm**
   - Thu thập log, metric, checkpoint ID.
   - Ghi chép RCA: nguyên nhân gốc, biện pháp phòng ngừa.
   - Cập nhật tài liệu và automation (alert mới, runbook update).

## 4. Tình huống phổ biến & xử lý
### Kafka backlog tăng
- **Triệu chứng**: `kafka_consumer_fetch_manager_metrics_records_lag_max` > 5000.
- **Hành động**:
  1. Check Flink job throughput (`flink_jobmanager_job_latency`).
  2. Rescale job (tăng parallelism), hoặc tăng partitions topic (theo hướng dẫn Kafka `kafka-topics.sh`).
  3. Kiểm tra GC container, allocate thêm CPU.

### Flink job restart liên tục
- **Triệu chứng**: Alert `FlinkJobRestarting`, logs hiển thị lỗi schema.
- **Hành động**:
  1. Inspect log qua Loki `container="flink-jobmanager"`.
  2. Nếu schema thay đổi → cập nhật Paimon type mapping (`allow_non_string_to_string` ...).
  3. Restore checkpoint sau khi deploy JAR mới.

### Cassandra node down
- **Triệu chứng**: `nodetool status` cho `DN` hoặc `UN` thiếu.
- **Hành động**:
  1. Check container log (`docker compose logs cassandra-nodeX`).
  2. Kiểm tra disk (heap) theo doc Cassandra; adjust `MAX_HEAP_SIZE`.
  3. Nếu node không phục hồi, khởi động container mới, cho phép bootstrap.

### Paimon/Nessie không commit được
- **Triệu chứng**: Flink sink throw error on commit.
- **Hành động**:
  1. Kiểm tra Nessie health (port 19120).
  2. Sử dụng `nessie` CLI xem conflict, merge/resolution.
  3. Đảm bảo MinIO reachable, disk free (metric `minio_cluster_disk_free_bytes`).

### Kafka Connect connector lỗi
- **Triệu chứng**: `kafka_connect_worker_connector_count` giảm đột ngột hoặc `kafka_connect_connector_failed_task_count` > 0.
- **Hành động**:
   1. Vào Grafana panel Kafka Connect để xác nhận connector cụ thể.
   2. Kiểm tra log `docker compose logs connect` để lấy stacktrace.
   3. Restart connector qua REST API `POST /connectors/{name}/restart` sau khi khắc phục cấu hình.

### Trino backlog tăng
- **Triệu chứng**: `trino_execution_queuedqueries` tăng cao, dashboard hiển thị queued > 0 liên tục.
- **Hành động**:
   1. Kiểm tra tài nguyên cluster (panel MinIO capacity, cAdvisor CPU).
   2. Xác minh query nặng qua Trino Web UI (8081) và cân nhắc kill (`/v1/query/{queryId}/killed`).
   3. Scale thêm worker Spark/Trino nếu workload dài hạn.

### MySQL/PostgreSQL connection saturation
- **Triệu chứng**: `mysql_global_status_threads_connected` hoặc `pg_stat_database_numbackends` vượt ngưỡng (ví dụ > 90% max).
- **Hành động**:
   1. Liệt kê session (`SHOW PROCESSLIST`, `SELECT * FROM pg_stat_activity`).
   2. Giảm pool size của ứng dụng, kiểm tra slow query.
   3. Tăng tài nguyên hoặc replica đọc nếu cần.

## 5. Bảng liên hệ on-call
| Vai trò | Kênh | SLA phản hồi |
| --- | --- | --- |
| Data Platform On-call | Slack #data-ops | 15 phút |
| Kafka SME | Slack #kafka | 30 phút |
| Cassandra SME | PagerDuty | 30 phút |
| Infra | Email infra@company.com | 1 giờ |

## 6. Checklist sau phục hồi
- [ ] Alert đã clear trong Alertmanager.
- [ ] Checkpoint/Savepoint cập nhật.
- [ ] Dữ liệu kiểm tra chéo (Spark/Trino) hợp lệ.
- [ ] Ticket ITSM chuyển trạng thái Resolved.
- [ ] RCA document lưu vào wiki nội bộ.

Runbook này cần được review hàng quý hoặc sau mỗi sự cố lớn.
