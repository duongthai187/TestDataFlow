# Runbook: Schema Drift (MySQL Producer Changes)

## 1. Purpose
Hướng dẫn xử lý sự cố khi producer thay đổi schema MySQL không theo quy trình (schema drift), khiến Debezium/Kafka Connect/consumers (Flink) lỗi. Áp dụng cho môi trường demo DataFlow.

## 2. Detection Signals
- Alert `SchemaDriftDetected` từ Prometheus (khi connector báo lỗi schema).
- Grafana panel Kafka Connect error tăng (`kafka_connect_connector_failed_task_count`).
- Debezium connector status `FAILED`, logs chứa `UnknownField` hoặc `Schema change` warning.
- Flink job trong dashboard hiển thị restart liên tục (`flink_jobmanager_job_numRestarts`).
- Synthetic chaos script output thông báo cột mới/đã gỡ.

## 3. Immediate Actions
1. **Kiểm tra trạng thái connector**:
   ```bash
   curl -s http://localhost:8083/connectors | jq
   curl -s http://localhost:8083/connectors/<connector>/status | jq
   ```
2. **Inspect logs**:
   ```bash
   docker compose logs connect --tail=200 | grep -i "schema"
   ```
3. **Xem schema hiện tại**: `docker compose exec -T mysql mysql -uroot -proot -e "SHOW COLUMNS FROM oltp.orders"` (ví dụ bảng bị thay đổi).
4. **Kiểm tra downstream**: Flink logs (`docker compose logs flink-jobmanager`), Support/Notification service log nếu nhận event sai schema.

## 4. Chaos Drill / Verification
- Tạo drift:
  ```bash
  make chaos-schema-drift ARGS="--table oltp.orders --column unexpected_field"
  ```
- Hoàn tác:
  ```bash
  make chaos-schema-drift ARGS="--table oltp.orders --column unexpected_field --revert"
  ```
- Script trả JSON ghi nhận DDL đã áp dụng, trạng thái MySQL, output connector.

## 5. Root Cause Exploration
- Deploy app tự ý ALTER TABLE.
- Migration script thiếu review.
- Debezium không tự nhận change (thiếu cấu hình `database.history`?).
- Downstream schema registry phiên bản cũ.

## 6. Remediation Steps
1. **Rollback schema**: nếu drift không hợp lệ, chạy SQL `ALTER TABLE ... DROP COLUMN` hoặc dùng script `--revert`.
2. **Cập nhật consumer**: nếu thay đổi hợp lệ → cập nhật event schema, Avro/Pydantic models, Flink job mapping.
3. **Restart connector**: sau khi schema đúng, `curl -X POST .../restart` hoặc `resume` nếu đang paused.
4. **Validate data**: chạy query kiểm tra dữ liệu, confirm Flink job healthy.
5. **Cập nhật quy trình phát hành**: enforce migration review, contract tests.

## 7. Postmortem Checklist
- [ ] Alert clear, connector quay lại trạng thái `RUNNING`.
- [ ] Log RCA: ai thay đổi schema, thời gian, impact.
- [ ] Cập nhật test (Integration/contract) để phát hiện sớm.
- [ ] Nếu drift hợp lệ: cập nhật documentation & schema registry.

## 8. References
- Chaos script: `scripts/chaos/simulate_schema_drift.py`
- Incident doc: `docs/monitoring/incident-runbook.md` mục "Schema drift".
- Prometheus rules: `monitoring/prometheus/rules/general-rules.yml`.
