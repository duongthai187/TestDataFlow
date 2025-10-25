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
   - Theo dõi Slack channel `#data-ops`; mọi alert `severity=high|critical` phải xuất hiện từ bot Alertmanager. Nếu không thấy, kiểm tra biến môi trường `ALERTMANAGER_SLACK_WEBHOOK_URL` và log container `alertmanager`.
   - Agent CS hoặc user báo lỗi -> tạo ticket.
2. **Chuẩn đoán**
   - Kiểm tra `docker compose ps --format "table {{.Name}}\t{{.State}}\t{{.Health}}"`, xác nhận container. Health check `healthy` phản ánh việc endpoint `/health` phản hồi OK; nếu `starting`/`unhealthy`, xem log `docker compose logs <service>` để xử lý trước khi tác động downstream.
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

### Debezium/MySQL replication lag
- **Triệu chứng**: Alert `CdcReplicationLagHigh`, panel Grafana hiển thị connector Debezium paused/lag cao (ví dụ `kafka_connect_source_task_lag_millis`). Topic CDC tăng backlog, downstream Flink không nhận kịp.
- **Hành động**:
   0. Tái hiện tình huống bằng `make chaos-replication-lag ARGS="--connect-url http://connect:8083 --rows 200"`. Script `scripts/chaos/simulate_replication_lag.py` sẽ pause connector, ghi dữ liệu vào MySQL và báo cáo binlog delta để kiểm chứng alert.
   1. Vào Kafka Connect UI/API (`GET /connectors/<name>/status`) để xác nhận state. Nếu connector bị PAUSED hoặc FAILED, xem log `docker compose logs connect`.
   2. Kiểm tra Debezium error (`SHOW MASTER STATUS` để xem binlog position). Nếu seen `mysql` backlog, confirm script output `binlogPositionDelta`.
   3. Resume connector (`POST /connectors/<name>/resume`) hoặc redeploy cấu hình (nếu schema thay đổi). Đảm bảo offset storage topic không lỗi bằng `docker compose logs connect`.
   4. Sau khi connector chạy lại, so sánh panel Grafana và script chaos output; đảm bảo `rowCountDelta` về 0 và lag giảm. Nếu lag vẫn cao → scale Kafka Connect worker hoặc xem xét chia nhỏ table.

### Schema drift (producer thay đổi schema bất ngờ)
- **Triệu chứng**: Debezium connector báo lỗi khi parse event, Flink job fail với thông báo field mismatch, alert `SchemaDriftDetected` bật. Grafana panel Kafka Connect error tăng, log connect xuất hiện `UnknownField`.
- **Hành động**:
   0. Dùng `make chaos-schema-drift ARGS="--table oltp.orders --column unexpected_field"` để thêm cột bất ngờ (script `scripts/chaos/simulate_schema_drift.py`). Sau diễn tập chạy lại với `--revert` để gỡ cột.
   1. Xem log connector (`docker compose logs connect`) tìm chi tiết field sai. Đồng thời kiểm tra `SHOW COLUMNS FROM <table>` để xác nhận cột mới.
   2. Cập nhật schema downstream (ví dụ Avro/Trino) hoặc rollback thay đổi: dùng script với `--revert` hoặc SQL `ALTER TABLE ... DROP COLUMN`.
   3. Sau khi sửa, restart connector (`POST /connectors/<name>/restart`) rồi theo dõi metric `kafka_connect_connector_failed_task_count` về 0. Kiểm tra lại Flink job đã chạy bình thường.
   4. Cập nhật quy trình phát hành schema để tránh drift, bổ sung kiểm thử contract.

### Cassandra reservation TTL quá ngắn dẫn tới oversell
- **Triệu chứng**: Alert `InventoryOversellRisk` bật, metric `inventory_reservation_expired_total` tăng bất thường, panel Grafana hiển thị số lượng reservation hết hạn trong vài phút và số order fail vì thiếu hàng.
- **Hành động**:
   0. Diễn tập bằng `make chaos-ttl-oversell ARGS="--keyspace inventory --table reservations --ttl 60"` (script `scripts/chaos/simulate_ttl_oversell.py`). Theo dõi panel inventory để xác nhận alert hoạt động; dùng `--revert --previous-ttl <old>` để khôi phục TTL.
   1. Kiểm tra cấu hình TTL hiện tại: `docker compose exec cassandra-seed cqlsh -e "DESCRIBE TABLE inventory.reservations"`.
   2. Nếu TTL vô tình bị giảm (deploy/DDL sai), khôi phục giá trị cũ bằng `ALTER TABLE ... WITH default_time_to_live = <baseline>`.
   3. Rà soát job batch/cron liên quan TTL để đảm bảo không xóa dữ liệu sớm; cập nhật automation để fail open khi TTL < ngưỡng.
   4. Xác nhận metric `inventory_reservation_active_total` phục hồi và alert clear trước khi kết thúc sự cố.

### Fulfillment artifacts backlog (MinIO hold)
- **Triệu chứng**: Alert `FulfillmentDelay` hoặc panel Grafana `fulfillment_lag_minutes` > 10, biểu đồ MinIO `fulfillment_artifacts_backlog_objects`/`fulfillment_artifacts_backlog_bytes` tăng. Support timeline không cập nhật trạng thái shipment mới, khách hàng báo chưa nhận được nhãn vận chuyển.
- **Hành động**:
   0. Khi cần diễn tập hoặc tái hiện, chạy `make chaos-fulfillment-delay ARGS="--count 25 --hold-minutes 30 --support-ticket-id <ticket>"`. Script `scripts/chaos/simulate_fulfillment_delay.py` sẽ tạo nhãn thử trong bucket MinIO `fulfillment-artifacts` với metadata `hold-until`, ghi log JSON và (nếu cung cấp `--support-ticket-id`) gọi API `/support/cases/{id}?includeTimeline=true` để xác nhận timeline đứng.
   1. Kiểm tra dashboard Grafana phần Fulfillment: panel backlog, heatmap thời gian kể từ sự kiện `status.shipped`. Đối chiếu `prometheus` query `sum(minio_objects{bucket="fulfillment-artifacts",prefix="chaos/fulfillment-delay/"})` hoặc metric tuỳ chỉnh `fulfillment_artifacts_backlog_objects` (nếu collector đã export) để xác nhận backlog thực tế.
   2. Kiểm tra container `fulfillment-service` và worker xử lý label (nếu có): `docker compose logs fulfillment-service` để xem retry tải lên. Đảm bảo MinIO vẫn healthy (`curl -sf http://localhost:9000/minio/health/live`). Nếu nhiều object ở prefix `pending/`, xác nhận pipeline copy sang `ready/` đang chạy.
   3. Khi backlog là giả lập (chaos script), xoá bằng `make chaos-fulfillment-delay ARGS="--revert --support-ticket-id <ticket>"`; script sẽ liệt kê và gỡ object đã tạo, đồng thời log tổng dung lượng đã giải phóng. Nếu backlog từ hệ thống thật, cân nhắc di chuyển thủ công: `mc ls minio/fulfillment-artifacts/pending/`, tải về gói nhãn rồi đẩy lại vào prefix `ready/` sau khi xác minh.
   4. Khôi phục dịch vụ: đảm bảo job/worker tạo nhãn hoạt động lại, support timeline có sự kiện mới (có thể refresh bằng endpoint `/support/cases/{id}/timeline/refresh`). Theo dõi alert cho tới khi `fulfillment_lag_minutes` < 5 trong 2 chu kỳ rồi đóng sự cố.

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

### Thông báo gửi thất bại hàng loạt
- **Triệu chứng**: Alert `NotificationFailureRateHigh` kích hoạt, panel Grafana "Notification send rate" hiển thị tỷ lệ thất bại > 20% hoặc các alert `NotificationRateLimitedBurst`, `NotificationOptOutSpike`, `NotificationRateLimiterErrors` đồng thời bật. Metric `notification_events_dropped_total{reason=~"rate_limited|opted_out|invalid_payload"}` tăng bất thường; nếu Redis gặp vấn đề, `notification_rate_limit_errors_total{operation=*}` sẽ nhảy.
- **Hành động**:
   0. Khi cần tái hiện alert để diễn tập/kiểm thử, chạy `make notification-chaos-provider ARGS="--base-url <notification-url> --count 10"` (script `scripts/chaos/notification_provider_failure.py`) để tạo 10 notification giả và buộc `/fail`; metric `notification_failure_total` sẽ tăng tương ứng.
   0b. Để kiểm chứng alert `NotificationRateLimiterErrors`, sử dụng `make notification-chaos-redis ARGS="--base-url <notification-url>"`. Script `scripts/chaos/notification_redis_outage.py` sẽ tạm dừng container Redis, gửi một loạt notification, đợi metric cập nhật rồi khởi động lại Redis và xác nhận `notification_rate_limit_errors_total{operation=*}` tăng.
   1. Mở dashboard Grafana `Dataflow Overview`, theo dõi các panel "Notification send rate", "Notification rate limited" và "Notification drops by reason" để xác định channel bị ảnh hưởng. Đối chiếu thêm "Opt-outs & preference updates" để xem biến động `notification_opt_out_total`.
   2. Nếu tăng `NotificationRateLimitedBurst`, kiểm tra cấu hình Redis rate limiter (`notification_rate_limit`, `notification_rate_window_seconds`) và lưu lượng chiến dịch hiện tại; tạm thời giảm batch size hoặc giãn lịch gửi trước khi nâng quota. Đồng thời quan sát `notification_rate_limit_errors_total{operation=*}` để xác định lỗi kết nối Redis và cân nhắc chuyển sang chế độ fail-open (service sẽ tự động cho phép khi Redis lỗi nhưng cần khắc phục sớm).
   3. Nếu lý do `invalid_payload` hoặc `unsupported_topic` tăng, truy vấn Loki `container="notification-service"` để xem stacktrace, xác thực schema sự kiện nguồn (support/order/fulfillment) và rollback thay đổi gây lỗi nếu cần.
   4. Nếu alert `NotificationOptOutSpike` bật, phối hợp marketing để rà soát nội dung chiến dịch, tạm dừng automation gây phiền nhiễu và kiểm tra trạng thái opt-in qua API `/notifications/preferences/{customerId}`.
   5. Chạy synthetic probe `make notification-probe ARGS="--base-url <notification-url>"` (hoặc trực tiếp `python scripts/synthetic/notification_probe.py`) để đảm bảo flow create/send hoạt động và metric tăng đúng (`notification_sent_total`, `notification_send_latency_seconds_count`). Lưu output JSON vào hồ sơ sự cố để so sánh sau này.
   6. Sau khi khắc phục, gửi thử một notification bằng API `/notifications/{id}/send` hoặc lập batch nhỏ để xác nhận; theo dõi lại các panel trong 15 phút, bảo đảm alert clear và tỷ lệ thất bại < 5%.

### Timeline support chậm hoặc backlog đính kèm tăng
- **Triệu chứng**: Alert `SupportTimelineLatencyHigh`, `SupportTimelineCollectionFailures` hoặc `SupportTimelineCacheErrors` bật; panel "Support timeline p95 latency" vượt quá 2 giây trong 10 phút, `support_timeline_collect_seconds{source="remote"}` tăng mạnh, `support_timeline_cache_events_total{event=~"miss|error"}` nhảy cao hoặc `support_timeline_collection_failures_total{stage=~"cache|cache_decode"}` xuất hiện. Đồng thời alert `SupportAttachmentBacklogHigh`/`SupportAttachmentGrowthRapid` hoặc metric `support_attachment_backlog_bytes`/`support_attachment_backlog_files` tăng liên tục.
- **Hành động**:
   1. Truy cập Grafana panel nói trên để xác định nguồn (cache hay remote). Nếu cache miss/ error tăng bất thường, kiểm tra Redis (`SERVICE_REDIS_URL`) và bảo đảm TTL đủ (`timeline_cache_ttl_seconds`).
   2. Mở GitHub Actions workflow **Support Synthetic Probe** để xem kết quả chạy gần nhất (cron 02:00 UTC). Nếu workflow thất bại, tải artifact `support-service-logs` để lấy log `uvicorn`/output synthetic probe làm dữ liệu chẩn đoán.
   3. Kiểm tra log `support-service` (Grafana Loki) để phát hiện lỗi gọi downstream (`order-service`, `payment-service`, `fulfillment-service`). Nếu có lỗi HTTP 5xx, cân nhắc degrade timeline bằng cách vô hiệu hóa tạm thời các nguồn qua `SERVICE_ORDER_SERVICE_URL`/`SERVICE_PAYMENT_SERVICE_URL`.
   4. Chạy synthetic probe `make support-probe ARGS="--base-url <support-url>"` (hoặc trực tiếp `python scripts/synthetic/support_timeline_probe.py`) để xác thực thời gian phản hồi từ góc nhìn người dùng; lưu output JSON vào sự cố để theo dõi.
   5. Với backlog attachment tăng, kiểm tra dung lượng thư mục `support_attachment_dir`; nếu gần đầy, dùng script `make support-offload ARGS="--age-days 30"` (hoặc `--dry-run` để audit) nhằm chuyển dữ liệu sang archive/cold storage. Đồng thời xác minh các API `/support/cases/{id}/attachments` vẫn trả về danh sách trong thời gian hợp lý (< 1s).
   6. Sau khi xử lý, xóa cache timeline bằng endpoint `/support/cases/{id}/timeline/refresh`, xác nhận panel latency trở về < 500 ms và backlog ổn định. Cập nhật lại synthetic probe để chắc chắn không còn cảnh báo.

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
