# Data Governance Cheatsheet

## 1. Quản lý schema & type mapping
- Sử dụng Apache Paimon làm định dạng bảng chính. Khi ingest CDC, tận dụng các tham số type mapping được tài liệu Apache Paimon cung cấp:
  - `--type_mapping char-to-string`: chuyển CHAR/VARCHAR từ MySQL sang STRING, tránh mismatch độ dài.
  - `--type_mapping tinyint1-not-bool`: giữ nguyên `TINYINT(1)` thay vì chuyển thành boolean.
  - `--type_mapping allow_non_string_to_string`: cho phép chuyển kiểu số sang STRING khi upstream thay đổi.
- Luôn chạy job action Paimon với `-Dpipeline.name=<job-name>` để đặt tên pipeline (doc Paimon CDC).
- Khi thêm cột mới: tạo branch `nessie` mới (`nessie branch create inventory-v2`), apply `ALTER TABLE`, validate, sau đó merge.

## 2. Quản lý phiên bản bảng
- Project Nessie lưu commit/branch cho warehouse `s3://lakehouse/warehouse`.
- Quy định:
  1. Use case mới -> branch `feature/<usecase>`.
  2. Sau khi kiểm thử, merge vào `main` thông qua `nessie merge`.
  3. Tag version release: `nessie tag create release-2025-10-16 --hash <commit>`.
- Lưu commit hash vào báo cáo (finance, marketing) để audit "data as of".

## 3. Quy trình thay đổi schema
1. Stakeholder mở ticket mô tả thay đổi.
2. Data engineer cập nhật Paimon schema trong branch Nessie, đồng thời cập nhật Trino/Doris catalog nếu cần.
3. Chạy pipeline thử trong môi trường staging (sử dụng compose copy) với dataset mẫu.
4. Khi pass test, merge branch, ghi chép vào `CHANGELOG.md`.
5. Cập nhật tài liệu `docs/usecases` liên quan.

## 4. DQ Rules (Data Quality)
- Tạo job Spark nightly kiểm tra:
  - Tính tổng `gross_amount` vs `net_amount` (Finance).
  - `inventory_snapshot.available_qty >= 0`.
  - `fraud_signals.risk_score` trong [0,100].
- Lưu kết quả vào Paimon `dq_results`. Nếu rule fail, phát alert Prometheus.

## 5. Catalog chuẩn hoá
- Trino catalog structure:
  - `paimon.commerce.orders`
  - `paimon.commerce.payments`
  - `paimon.analytics.fraud`
- Sử dụng `trino/catalog/*.properties` để ánh xạ Nessie URI (`http://nessie:19120/api/v1`) và MinIO S3 endpoint.

## 6. Bảo mật & tuân thủ
- Bật TLS/credential cho MinIO và Kafka trong môi trường prod.
- Mask dữ liệu nhạy cảm (PII) khi export: Flink job filter/mask email trước khi ghi Paimon.
- Lưu log truy cập trong CouchDB/Elastic (ngoài scope) để audit.

## 7. Checklist onboarding pipeline mới
- [ ] Đăng ký schema trong bảng metadata (PostgreSQL).
- [ ] Thiết lập topic Kafka với naming convention `domain.entity.event`.
- [ ] Cập nhật runbook monitoring (thêm alert rule nếu cần).
- [ ] Viết tài liệu trong `docs/usecases` mô tả pipeline.
- [ ] Tạo dashboard Grafana/Trino query mẫu.

Tài liệu này đảm bảo mỗi thay đổi được kiểm soát và dễ phục hồi nhờ khả năng versioning và schema evolution mà Apache Paimon/Nessie cung cấp.
