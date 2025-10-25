# Runbook: CDC Replication Lag (Debezium / Kafka Connect)

## 1. Purpose
Hướng dẫn xử lý tình huống độ trễ CDC tăng cao do connector Debezium/Kafka Connect bị pause, backlog binlog hoặc kết nối MySQL chậm. Áp dụng cho môi trường demo DataFlow.

## 2. Detection Signals
- Alert Prometheus `CdcReplicationLagHigh` (severity warning/critical).
- Grafana `Dataflow Overview` → panel "CDC replication lag" hiển thị `kafka_connect_source_task_lag_millis` tăng.
- Kafka Connect exporter metrics:
  - `kafka_connect_source_task_lag_millis{connector="mysql-oltp"}`
  - `kafka_connect_connector_failed_task_count`
- MySQL binlog biến động: `SHOW MASTER STATUS` vị trí tăng nhanh.
- Synthetic chaos script output (khi diễn tập) báo `state="PAUSED"`, `binlogPositionDelta` lớn.

## 3. Immediate Actions
1. **Xác nhận alert** trên Alertmanager/Slack; ghi nhận thời gian kích hoạt.
2. **Kiểm tra trạng thái connectors**:
   ```bash
   curl -s http://localhost:8083/connectors | jq
   curl -s http://localhost:8083/connectors/<connector>/status | jq
   ```
3. **Đo lag qua metrics**: `curl -s http://localhost:9404/metrics | grep kafka_connect_source_task_lag_millis`.
4. **Inspect Kafka Connect logs**: `docker compose logs connect --tail=200`.
5. **Kiểm tra MySQL**: đảm bảo container healthy `docker compose ps mysql`; chạy `SHOW PROCESSLIST` xem query dài.

## 4. Chaos Drill / Verification
- Mô phỏng bằng script:
  ```bash
  make chaos-replication-lag ARGS="--connect-url http://connect:8083 --rows 100 --pause-duration 20"
  ```
- Script thực hiện: pause connectors → insert dữ liệu → chờ → resume. Output JSON gồm trạng thái connectors, delta binlog, metric snapshot.
- Sau khi drill, theo dõi Grafana/Prometheus để chắc alert bật đúng; dùng `--skip-metrics` nếu muốn chỉ kiểm tra pause/resume.

## 5. Root Cause Exploration
- Connector bị PAUSED (manual hoặc lỗi schema) → check `tasks[ ].state`.
- MySQL quá tải / lock dài → `SHOW ENGINE INNODB STATUS`.
- Kafka Connect worker thiếu tài nguyên (CPU/RAM) → xem `docker stats` hoặc Grafana panel Connect.
- Network giữa MySQL và Connect bất ổn → kiểm tra log timeout.
- Schema drift gây lỗi (liên quan runbook khác) → `connector.state=FAILED`.

## 6. Remediation Steps
1. **Nếu connector PAUSED**: `curl -X POST http://localhost:8083/connectors/<connector>/resume`.
2. **Nếu FAILED**: xem log, khắc phục nguyên nhân (schema mismatch) rồi `restart`.
3. **Giảm backlog**: đảm bảo MySQL hoạt động, consider tăng pause duration cho script; trong thực tế scale Connect worker.
4. **Xác nhận lag giảm**: metric `kafka_connect_source_task_lag_millis` < 1000 trong 5 phút.
5. **Check downstream**: Flink jobs nhận dữ liệu (no `backpressure`), topic Kafka backlog giảm.
6. **Sau drill**: script đã resume; nếu cần xoá bảng chaos `_chaos_replication_events`:
   ```bash
   docker compose exec -T mysql mysql -uroot -proot -e "DROP TABLE IF EXISTS oltp.chaos_replication_events"
   ```

## 7. Postmortem Checklist
- [ ] Alert cleared và channel nhận cảnh báo đủ.
- [ ] Ghi log sự cố (thời gian, nguyên nhân, action).
- [ ] Nếu do schema hoặc config, cập nhật CI/cảnh báo để phòng ngừa.
- [ ] Bổ sung test/synthetic nếu thiếu.

## 8. References
- Chaos script: `scripts/chaos/simulate_replication_lag.py`
- Prometheus rules: `monitoring/prometheus/rules/general-rules.yml` (mục replication lag).
- Docs: `docs/monitoring/incident-runbook.md` mục "Debezium/MySQL replication lag".
