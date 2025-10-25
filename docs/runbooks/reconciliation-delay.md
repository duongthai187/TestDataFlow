# Runbook: Finance Reconciliation Delay

## 1. Purpose
Xử lý tình huống job đối soát tài chính (finance reconciliation) chạy chậm hoặc không tạo báo cáo sau mốc SLA (30 phút). Áp dụng cho môi trường demo khi Spark/Doris batch bị chậm, CDC feed từ MySQL/PostgreSQL không đủ dữ liệu.

## 2. Detection Signals
- Alert Prometheus `FinanceReconciliationLagHigh` (khi metric `finance_reconciliation_age_minutes` > 30).
- Grafana dashboard "Checkout Flow" hoặc "Finance" panel hiển thị thời gian cập nhật báo cáo cuối cùng (`finance_reconciliation_last_updated_timestamp`).
- Synthetic check (khi có) ghi nhận job chưa tạo artifact trong MinIO `finance-reports/`.
- Nessie/Trino query report `SELECT max(run_ended_at) FROM finance_reconciliation_report` < `NOW() - interval '30 minutes'`.

## 3. Immediate Actions
1. **Xác nhận alert** qua Alertmanager; note severity/time.
2. **Kiểm tra Airflow/cron** (nếu sử dụng): `docker compose logs airflow-scheduler` hoặc job orchestrator.
3. **Quan sát Spark job**: `docker compose logs spark-master`/`spark-worker`; xem có job failure/out-of-memory.
4. **Kiểm tra nguồn dữ liệu**:
   - MySQL orders up-to-date (`SELECT MAX(updated_at) FROM oltp.orders`).
   - PostgreSQL payments (`SELECT MAX(updated_at) FROM payments`).
   - Kafka connect CDC lag (tham khảo runbook replication-lag).
5. **Kiểm tra MinIO** bucket `finance-reports/` timestamp file mới nhất.

## 4. Synthetic Drill / Manual Verification
*(Chưa có script tự động; thực hiện thủ công)*
1. Tạm dừng job reconciliation (stop cron) hoặc tạo backlog dữ liệu (pause Debezium) để quan sát alert.
2. Sau khi drill, khởi động job và xác nhận metric giảm.
3. TODO: bổ sung script automation (Phase tiếp theo).

## 5. Root Cause Exploration
- CDC lag: dữ liệu chưa đến table staging → tham khảo runbook `replication-lag`.
- Spark job fail do schema mismatch (check log `finance_reconciliation_job`), missing column.
- Doris/MinIO hết dung lượng.
- Nessie merge conflict khiến branch không cập nhật.
- Credentials hết hạn truy cập MinIO/Paimon.

## 6. Remediation Steps
1. **Khôi phục nguồn dữ liệu** (resolve replication lag, schema drift).
2. **Rerun job**: `docker compose exec spark-master spark-submit ...` (theo script `jobs/finance_reconciliation.py`).
3. **Kiểm tra output**: xác nhận file mới trong MinIO `finance-reports/`, bảng Doris cập nhật.
4. **Update metric**: chạy script cập nhật `finance_reconciliation_last_updated_timestamp` (nếu job không đẩy metric → patch job).
5. **Communicate**: thông báo Finance khi job đã hoàn thành, cung cấp link báo cáo mới.

## 7. Postmortem Checklist
- [ ] Alert cleared và metric `finance_reconciliation_age_minutes` < 30.
- [ ] Ghi log sự cố (nguyên nhân, thời gian, dữ liệu bị ảnh hưởng).
- [ ] Xem xét tự động hoá (retry, SLA monitor) để tránh tái diễn.
- [ ] Cập nhật tài liệu và script nếu có thay đổi.

## 8. References
- Use case: `docs/usecases/finance-reconciliation.md`.
- Pipeline spec: `docs/design/pipelines.md`, `docs/design/ecommerce-microservices.md` (phần finance).
- Metric source: TODO (add to Prometheus exporter / job metrics).
