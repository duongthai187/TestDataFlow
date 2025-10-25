# Runbook: Cassandra TTL Oversell Risk

## 1. Purpose
Mô tả quy trình phát hiện và khắc phục tình huống TTL reservation Cassandra bị đặt quá thấp dẫn đến oversell tồn kho.

## 2. Detection Signals
- Alert `InventoryOversellRisk` bật (Prometheus rule).
- Grafana panel Inventory hiển thị `inventory_reservation_expired_total` tăng đột biến.
- Metric hỗ trợ: `inventory_reservation_active_total`, `inventory_reservation_expired_total`.
- Synthetic chaos script output báo TTL mới và số lệnh CQL đã chạy.

## 3. Immediate Actions
1. **Xác nhận alert**: kiểm tra Alertmanager/Slack.
2. **Audit TTL**: `docker compose exec cassandra-seed cqlsh -e "DESCRIBE TABLE inventory.reservations"`.
3. **Kiểm tra log service Inventory/Checkout** để xem lỗi oversell.
4. **Xem dashboard**: panel reservations active, order fail do thiếu hàng.

## 4. Chaos Drill / Verification
- Giảm TTL:
  ```bash
  make chaos-ttl-oversell ARGS="--keyspace inventory --table reservations --ttl 60"
  ```
- Hoàn tác:
  ```bash
  make chaos-ttl-oversell ARGS="--revert --previous-ttl 3600"
  ```
- Script trả JSON liệt kê command CQL, kết quả `after_cql` (nếu có), delta TTL.

## 5. Root Cause Exploration
- Migration áp dụng TTL sai.
- Worker batch cleanup xóa quá sớm.
- Config service set TTL mới qua driver.
- Chaos drill giữ nguyên TTL do chưa revert.

## 6. Remediation Steps
1. **Khôi phục TTL chuẩn** bằng `ALTER TABLE ... WITH default_time_to_live = <baseline>`.
2. **Nếu script được dùng**: chạy lại `make chaos-ttl-oversell` với `--revert` và cung cấp `--previous-ttl` chuẩn.
3. **Seed reservation test** (tuỳ chọn) qua `--after-cql` để xác nhận TTL mới hoạt động.
4. **Theo dõi metric**: bảo đảm `inventory_reservation_expired_total` trở về baseline, alert clear.
5. **Rà soát deployment/config** để ngăn TTL bị override.

## 7. Postmortem Checklist
- [ ] Alert clear trong Alertmanager.
- [ ] TTL baseline được ghi nhận và kiểm tra.
- [ ] Cập nhật doc/config nếu TTL chuẩn thay đổi.
- [ ] Bổ sung guardrail (monitor TTL) nếu thiếu.

## 8. References
- Chaos script: `scripts/chaos/simulate_ttl_oversell.py`
- Incident doc: `docs/monitoring/incident-runbook.md` phần Cassandra TTL.
- Prometheus rules: `monitoring/prometheus/rules/general-rules.yml`.
