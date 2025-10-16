# Case study: Kafka consumer lag cao

## Bối cảnh
- Alert `KafkaConsumerLagHigh` trên Prometheus được kích hoạt (lag > 10.000 message).
- Ảnh hưởng: pipeline fraud detection sử dụng Flink đọc topic `commerce.oltp.orders` bị chậm.

## Quy trình xử lý
1. **Xác nhận cảnh báo**
   - Truy cập Grafana dashboard *Dataflow Overview*, panel `Kafka consumer lag` hiển thị nhóm tiêu thụ `fraud-detection` tăng mạnh.
   - Dùng Prometheus query `kafka_consumergroup_lag{group="fraud-detection"}` để xem partition nào bị backlog.
2. **Kiểm tra job Flink**
   - Truy cập Flink UI (`http://localhost:8088`) hoặc dùng REST API `GET /jobs` để xem trạng thái job `fraud_detection_pipeline`.
   - Panel `Flink job restarts` trong Grafana cho thấy không có restart, nhưng throughput giảm.
   - Kiểm tra metric `flink_taskmanager_Status_JVM_CPU_Load` qua Prometheus để đảm bảo TaskManager không quá tải.
3. **Hành động khắc phục**
   - Tăng parallelism: `docker compose exec flink-jobmanager ./bin/flink list` xác nhận job ID, sau đó `./bin/flink rescale <jobId> 4` để tăng số TaskManager slot theo hướng dẫn trong tài liệu Apache Flink REST.
   - Nếu cần, scale container TaskManager: `docker compose up -d --scale flink-taskmanager=2`.
4. **Xác nhận**
   - Theo dõi Grafana: lag giảm dần về dưới ngưỡng trong 5-10 phút.
   - Prometheus alert chuyển trạng thái `resolved`.
5. **Hậu kiểm**
   - Ghi lại root cause: surge đơn hàng flash sale.
   - Cập nhật runbook thêm bước scale tự động (có thể dùng `docker compose` auto scaling hoặc orchestrator).

## Bài học
- Theo dõi panel Kafka lag thường xuyên để phát hiện sớm.
- Sẵn sàng script rescale Flink + autoscaling TaskManager.
- Cân nhắc tăng partition topic để tránh bottleneck trong các đợt cao điểm.
