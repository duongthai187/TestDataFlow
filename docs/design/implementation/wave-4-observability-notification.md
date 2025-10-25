# Wave 4 – Notification Observability Hardening

## 1. Objectives
- Đóng vòng quan sát (metrics → alert → dashboard → runbook) cho notification-service.
- Đảm bảo Alertmanager phát hiện được lỗi gửi, rate limit bất thường, opt-out spike, và có hướng dẫn xử lý rõ ràng.
- Chuẩn hóa panel Grafana phục vụ on-call, liên kết với runbook mới cập nhật.
- Xác nhận regression tests vẫn xanh sau khi bổ sung instrumentation.

## 2. Scope & Deliverables
| Hạng mục | Deliverable |
| --- | --- |
| Prometheus | `notification_sent_total`, `notification_failure_total`, `notification_rate_limited_total`, `notification_opt_out_total`, `notification_events_dropped_total`, `notification_send_latency_seconds`, `notification_preference_updates_total`, `notification_rate_limit_errors_total` được expose qua `/metrics`; scrape job `app-services` cập nhật. |
| Alerting | Alert rules `NotificationFailureRateHigh`, `NotificationRateLimitedBurst`, `NotificationOptOutSpike`, `NotificationRateLimiterErrors` trong `monitoring/prometheus/rules/general-rules.yml`. |
| Dashboard | Các panel "Notification send rate", "Notification rate limited", "Notification drops by reason", "Opt-outs & preference updates" trong `monitoring/grafana/provisioning/dashboards/json/dataflow-overview.json`. |
| Runbook | Mục "Thông báo gửi thất bại hàng loạt" trong `docs/monitoring/incident-runbook.md` mô tả quy trình phản ứng. |
| Docs | Update chiến lược observability (`docs/monitoring/chien-luoc-observability.md`) và README monitoring tổng quan. |

## 3. Implementation Summary
1. **Instrumentation**
   - Bổ sung counter/histogram trong `services/notification_service/app/metrics.py`.
   - Gắn metric tại `NotificationService.send_notification`, `fail_notification`, `update_preferences`, rate limiter enforcement, event handlers để cover success, failure, opt-out, rate-limit.
2. **Prometheus Integration**
   - Mở rộng scrape job `app-services` để lấy metric FastAPI services (port 8000).
   - Thêm quy tắc alert dựa trên tỷ lệ lỗi, rate limit increment và opt-out spike.
3. **Grafana Panels**
   - Bổ sung panel timeseries hiển thị send/fail rate, rate limited, drop reason, opt-out vs preference update.
4. **Runbook & Docs**
   - Runbook mới hướng dẫn 5 bước xử lý alert notification.
   - Chiến lược observability cập nhật KPI/alert notification.
   - README monitoring nêu rõ panel mới.
5. **Chaos Drill**
   - Script `scripts/chaos/notification_provider_failure.py` tái hiện lỗi provider, giúp kiểm chứng alert `NotificationFailureRateHigh` và hướng dẫn runbook.
   - Script `scripts/chaos/notification_redis_outage.py` tạm dừng Redis, gửi loạt notification và xác nhận `notification_rate_limit_errors_total` tăng để kiểm chứng alert `NotificationRateLimiterErrors`.
6. **Testing**
   - `pytest services/tests` (77 tests, 0 failures, 4 warnings) xác nhận không regression.

## 4. Operational Playbook
| Alert | Mô tả | Hành động phản ứng nhanh |
| --- | --- | --- |
| `NotificationFailureRateHigh` | Tỷ lệ lỗi > 20% trong 10 phút | Kiểm tra panel send rate; soi log provider, queue; cân nhắc failover provider. |
| `NotificationRateLimitedBurst` | Rate limit > 5 lần/5 phút | Xem lại quota Redis (`notification_rate_limit`), giảm batch hoặc giãn lịch gửi. |
| `NotificationOptOutSpike` | Opt-out tăng > 20/15 phút | Phối hợp marketing, tạm dừng chiến dịch, rà soát nội dung. |

## 5. Verification Checklist
- [x] `curl http://notification-service:8000/metrics` trả về các metric mới.
- [x] Prometheus job `app-services` hiển thị target `notification-service` trạng thái `UP`.
- [x] Grafana dashboard `Dataflow Overview` có 4 panel notification mới.
- [x] Alertmanager rule file có ba alert notification và `amtool check-config` pass.
- [x] Runbook incident đã cập nhật hướng dẫn `Thông báo gửi thất bại hàng loạt`.
- [x] `pytest services/tests` pass.

## 6. Follow-up Items
- [ ] Mở rộng observability tương tự cho support-service (timeline latency, attachment backlog) và fulfillment-service (carrier SLA).
- [x] Thiết lập synthetic test gửi notification định kỳ để kiểm tra alert chain (`scripts/synthetic/notification_probe.py`, workflow `Notification Synthetic Probe`).
- [x] Bổ sung scenario chaos (Redis down → metric/alert) và update runbook tương ứng.
- [x] Kết nối Alertmanager → Slack channel `#data-ops` để đảm bảo alert route thực thi.
