# Wave 4 – Support Observability Hardening

## 1. Objectives
- Bổ sung metric cho support-service để đo latency rebuild timeline và backlog đính kèm.
- Theo dõi lưu lượng ticket/conversation nhằm phát hiện xu hướng bất thường.
- Gắn metric vào dashboard Grafana và runbook để on-call phản ứng nhanh khi timeline chậm hoặc file tồn đọng.

## 2. Scope & Deliverables
| Hạng mục | Deliverable |
| --- | --- |
| Prometheus | Metric mới `support_timeline_collect_seconds`, `support_timeline_cache_events_total`, `support_timeline_collection_failures_total`, `support_attachment_stored_total`, `support_attachment_backlog_bytes`, `support_attachment_backlog_files`, `support_ticket_created_total`, `support_conversation_added_total`, `support_ticket_status_changed_total` được expose qua `/metrics` của support-service (bao gồm sự kiện cache `hit/miss/write/invalidate/error` và stage lỗi `http/cache/cache_decode/aggregate`). |
| Application | Instrumentation tại `SupportService`, `TimelineAggregator`, `LocalAttachmentStorage` để ghi nhận counter/gauge/histogram tương ứng. |
| Dashboard | Panel Grafana "Support timeline p95 latency", "Support attachment backlog", "Support timeline cache events", "Support timeline failure stages" trong `monitoring/grafana/provisioning/dashboards/json/dataflow-overview.json`. |
| Runbook | Mục "Timeline support chậm hoặc backlog đính kèm tăng" bổ sung trong `docs/monitoring/incident-runbook.md` (bao gồm alert `SupportTimelineCacheErrors`). |
| Docs | `chien-luoc-observability.md` và `monitoring/README.md` cập nhật phần support-service. |
| Tests | Bài test mới/điều chỉnh tại `services/tests/support_service/test_timeline_aggregator.py` và `test_support_api.py` xác nhận metric hoạt động. |

## 3. Implementation Summary
1. **Metric definitions**: `services/support_service/app/metrics.py` khai báo counter/histogram/gauge và hàm chuẩn hoá label.
2. **Domain instrumentation**: `SupportService` tăng counter khi tạo ticket, thêm conversation, đổi trạng thái; `LocalAttachmentStorage` đếm số file, nội dung type và cập nhật gauge backlog theo kích thước thật.
3. **Timeline instrumentation**:
   - Histogram `support_timeline_collect_seconds{source}` đo p95 cache vs remote.
   - Counter `support_timeline_cache_events_total{event}` theo dõi hit/miss/write/invalidate/error (đồng thời trigger alert `SupportTimelineCacheErrors`).
   - Counter lỗi `support_timeline_collection_failures_total{stage}` khi HTTP/convert lỗi.
4. **Dashboards**: panel mới hiển thị p95 latency (histogram_quantile) và backlog bytes/files.
5. **Runbook**: quy trình xử lý timeline chậm, backlog tăng (Redis, downstream API, storage capacity).
6. **Testing**: cập nhật unit test xác thực metric delta và gauge, chạy `pytest services/tests/support_service -q` sạch.

## 4. Operational Playbook
| Signal | Mô tả | Hành động nhanh |
| --- | --- | --- |
| `support_timeline_collect_seconds{source="remote"}` p95 > 2s | Timeline rebuild chậm (downstream timeout hoặc Redis cache trống). | Kiểm tra Redis TTL, log support-service, trạng thái order/payment/fulfillment API; cân nhắc degrade timeline hoặc tăng TTL. |
| `support_timeline_cache_events_total{event="miss"}` tăng mạnh | Cache miss bất thường (Redis lỗi hoặc invalidation nhiều). | Kiểm tra Redis availability, TTL; dùng `/support/cases/{id}/timeline/refresh` kiểm chứng. |
| `support_attachment_backlog_bytes` > ngưỡng đĩa | Backlog file đính kèm chưa purge. | Dọn dẹp storage, chuyển file sang offload bucket, mở rộng volume. |

## 5. Verification Checklist
- [x] `curl http://support-service:8000/metrics` hiển thị metric `support_timeline_collect_seconds_bucket` và `support_attachment_backlog_bytes`.
- [x] Grafana panel mới render dữ liệu từ Prometheus (sử dụng datasource `Prometheus`).
- [x] `support_attachment_stored_total{content_type="text/plain"}` tăng sau khi upload file qua API.
- [x] Tests `pytest services/tests/support_service/test_timeline_aggregator.py -q` và `pytest services/tests/support_service/test_support_api.py -q` pass.

## 6. Follow-up Items
1. Thêm alert Prometheus `SupportTimelineLatencyHigh` và `SupportAttachmentBacklogHigh` với ngưỡng rõ ràng, route về `#data-ops`.
2. Thu thập metric truy cập API `/support/cases/*` (request duration, status code) bằng middleware Prometheus để phát hiện lỗi 5xx.
3. Offload attachment backlog sang object storage (MinIO/S3) và chỉ giữ metadata trong DB.
4. Thiết lập synthetic check gửi Fulfillment event giả lập để đảm bảo timeline aggregator hoạt động ổn định.
