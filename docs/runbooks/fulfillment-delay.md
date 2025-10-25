# Runbook: Fulfillment Artifact Backlog (MinIO Hold)

## 1. Purpose
Mô tả quy trình phát hiện, chẩn đoán và khắc phục sự cố backlog artefact giao vận (label, packing slip) bị giữ lại trong MinIO làm chậm dòng fulfillment. Áp dụng cho môi trường local/demo của dự án DataFlow.

## 2. Signals & Detection
- Alert Prometheus `FulfillmentDelay` hoặc metric tuỳ chỉnh `fulfillment_lag_minutes` vượt ngưỡng (mặc định > 10 phút trong 5 phút).
- Grafana dashboard `Dataflow Overview` → panel "Fulfillment backlog" hiển thị tổng số artefact ở trạng thái pending.
- MinIO exporter:
  - `fulfillment_artifacts_backlog_objects`
  - `fulfillment_artifacts_backlog_bytes`
- Support timeline stale: API `GET /support/cases/{ticketId}?includeTimeline=true` trả về sự kiện fulfillment cũ (> 15 phút so với now).
- Synthetic probe (khi bật) báo `status=error` cho bước timeline refresh.

## 3. Immediate Actions
1. **Xác nhận alert**: kiểm tra Alertmanager route Slack/Email/Teams để đảm bảo cảnh báo đã bắn đúng receiver.
2. **Kiểm tra dashboard**: mở Grafana panel Fulfillment backlog → ghi nhận số object/prefix chờ xử lý và thời gian lâu nhất.
3. **Xem sức khỏe MinIO**: `docker compose ps minio` hoặc `curl -sf http://localhost:9000/minio/health/live`. Nếu MinIO lỗi → khôi phục trước khi xử lý backlog.
4. **Truy xét artefact**: sử dụng MinIO client hoặc script chaos (dry-run) để liệt kê object:
   ```bash
   poetry run python scripts/chaos/simulate_fulfillment_delay.py --dry-run --prefix pending/ --count 5
   ```
5. **Kiểm tra worker tạo label**: `docker compose logs fulfillment-service` hoặc job nền xử lý label để xem có lỗi upload/callback.

## 4. Synthetic Chaos & Verification
- **Tạo backlog giả lập**: 
  ```bash
  make chaos-fulfillment-delay ARGS="--count 25 --hold-minutes 30 --support-ticket-id <ticket>"
  ```
  Script tạo artefact prefix `chaos/fulfillment-delay/` trong bucket `fulfillment-artifacts`, đồng thời gọi API support để đo timeline.
- **Xoá backlog chaos**: 
  ```bash
  make chaos-fulfillment-delay ARGS="--revert"
  ```
- **Quan sát output**: script trả JSON chứa mẫu object, tổng bytes, thông tin docker-compose, kết quả probe support.

## 5. Root Cause Exploration
- Worker/cron không chuyển artefact từ `pending/` sang `ready/` (timeout khi gọi API carrier).
- MinIO quota đầy → upload thất bại (kiểm tra metric `minio_cluster_capacity_free_bytes`).
- Pipeline downstream (ví dụ Airflow job) bị dừng làm backlog không giảm.
- Sai cấu hình prefix hoặc credential MinIO trong `fulfillment-service` (`MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`).

## 6. Remediation Steps
1. **Giải phóng artefact**: nếu backlog là sự cố thật, dùng MinIO client:
   ```bash
   mc ls minio/fulfillment-artifacts/pending/
   mc mv minio/fulfillment-artifacts/pending/*.pdf minio/fulfillment-artifacts/ready/
   ```
   Hoặc trigger lại worker tạo label.
2. **Khôi phục dịch vụ**: restart worker/service gặp lỗi (`docker compose restart fulfillment-service`).
3. **Clean-up chaos** (nếu vừa diễn tập): chạy `make chaos-fulfillment-delay ARGS="--revert"`.
4. **Refresh timeline support**: `curl -X POST http://support-service:8000/support/cases/<ticketId>/timeline/refresh` để xác nhận timeline cập nhật.
5. **Theo dõi metric**: đảm bảo `fulfillment_lag_minutes` < 5 trong ≥ 2 chu kỳ scrape và backlog object giảm về baseline.

## 7. Postmortem Checklist
- [ ] Alert cleares & xác minh channel nhận cảnh báo đầy đủ.
- [ ] Ghi chú sự cố vào Incident log (thời gian, nguyên nhân, biện pháp).
- [ ] Nếu nguyên nhân vận hành: cập nhật SOP/automation (ví dụ thêm retry, cảnh báo dung lượng).
- [ ] Bổ sung test/synthetic probe nếu cần để phát hiện sớm hơn.
- [ ] Cập nhật tài liệu (README, runbook) nếu quy trình thay đổi.

## 8. References
- Chaos script: `scripts/chaos/simulate_fulfillment_delay.py`
- Makefile target: `make chaos-fulfillment-delay`
- Docs liên quan:
  - `docs/monitoring/README.md` – tổng quan monitoring & chaos drills.
  - `docs/monitoring/incident-runbook.md` – mục "Fulfillment artifacts backlog".
  - `docs/design/implementation/wave-4-ops-hardening.md` – kế hoạch tổng thể Wave-4.
