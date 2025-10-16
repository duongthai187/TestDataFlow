# Pipeline đối soát tài chính

## 1. Mục tiêu
- Hợp nhất dữ liệu đơn hàng (MySQL), thanh toán (PostgreSQL), vận chuyển (file log MinIO) để tạo báo cáo tài chính chính xác cuối ngày.
- Đảm bảo khả năng audit với version control (Nessie) và lưu hồ sơ lâu dài.
- SLA: Hoàn thành batch reconciliation < 30 phút sau khi kết thúc ngày giao dịch.

## 2. Kiến trúc kết hợp batch + realtime
```
Realtime: MySQL/PostgreSQL CDC -> Kafka -> Flink -> Paimon finance_fact (gần realtime)
Batch: Spark (đọc Paimon + file shipping) -> Doris/Trino báo cáo -> Lưu PDF/Excel
```
- Flink đảm bảo dữ liệu cập nhật liên tục, sẵn sàng cho báo cáo intraday.
- Spark chạy sau 23:59 và dùng `finance_fact` để đối chiếu với log giao nhận (MinIO).

## 3. Bảng dữ liệu
```sql
CREATE TABLE finance_fact (
  `order_id` BIGINT,
  `payment_id` BIGINT,
  `status` STRING,
  `gross_amount` DECIMAL(12,2),
  `net_amount` DECIMAL(12,2),
  `currency` STRING,
  `payment_provider` STRING,
  `shipping_cost` DECIMAL(12,2),
  `settlement_date` DATE,
  `updated_at` TIMESTAMP(3),
  PRIMARY KEY (`order_id`) NOT ENFORCED
) WITH (
  'bucket' = '4',
  'write-mode' = 'change-log'
);
```
- Dùng `SET 'table.exec.sink.upsert-materialize' = 'NONE';` (khuyến cáo Paimon).
- Sử dụng option type mapping nếu cần: `--type_mapping char-to-string`, `--type_mapping tinyint1-not-bool` hỗ trợ trong job action Paimon (theo doc Apache Paimon CDC).

## 4. Flink job (chạy liên tục)
```sql
INSERT INTO finance_fact
SELECT o.order_id,
       p.payment_id,
       p.status,
       o.total_amount,
       o.total_amount - o.discount - o.refund AS net_amount,
       o.currency,
       p.provider AS payment_provider,
       COALESCE(s.shipping_cost, 0) AS shipping_cost,
       CAST(p.event_time AS DATE) AS settlement_date,
       CURRENT_TIMESTAMP AS updated_at
FROM orders_cdc o
LEFT JOIN payments_cdc p ON o.order_id = p.order_id
LEFT JOIN shipping_events s ON o.order_id = s.order_id;
```
`shipping_events` được ingest bằng Spark streaming hoặc job Flink đọc từ file MinIO (S3) qua `filesystem` connector.

## 5. Batch Spark đối soát
- Lập lịch bằng Airflow (gợi ý) gọi script Spark sau mỗi ngày:
```bash
spark-submit \
  --packages org.apache.paimon:paimon-spark-3.5_2.12:0.8.0 \
  jobs/finance_reconcile.py --date 2025-10-15
```
- Job tải `finance_fact`, `payments_cdc` snapshot, `shipping_logs`, tính chênh lệch, ghi `finance_reconciliation_report` vào Doris.
- Lưu kết quả CSV/Parquet vào `s3://lakehouse/reports/<date>/`.

## 6. Governance & Audit
- Mỗi batch commit vào Nessie branch `finance-eod`, sau khi review merge vào `main`.
- Lưu hash commit `nessie/api/v1/trees` kèm báo cáo → dễ dàng truy vết.
- Log Paimon `CHANGELOG` phục vụ audit.

## 7. Kiểm soát chất lượng
- `Spark` so sánh `SUM(gross_amount)` giữa `finance_fact` và `payments`. Nếu lệch > 0.1%, raise alert (Prometheus metric custom push).
- Theo dõi job Flink qua metric `flink_jobmanager_job_numRestarts` (alert). Checkpoint đặt 5 phút.
- Dùng `Kafka Streams` (hoặc CLI) để kiểm tra lag topic `payments_cdc` (theo doc Kafka).

## 8. Quy trình lỗi điển hình
1. **Flink job fail vì schema thay đổi**: Kiểm tra log (Loki), cập nhật type mapping Paimon (ví dụ `--type_mapping allow_non_string_to_string`).
2. **Spark batch chậm**: Kiểm tra cluster resources, scale Spark worker, hoặc tăng partitions Paimon.
3. **Nessie merge conflict**: Sử dụng `nessie merge` CLI, review diff.

## 9. Deliverables
- Dashboard Doris/Trino: KPI doanh thu, tỷ lệ hoàn tiền, chi phí vận chuyển.
- Báo cáo PDF (tự động) attach commit hash Nessie.
- Lưu log reconciliation vào CouchDB để CS truy vết khi khách khiếu nại.
