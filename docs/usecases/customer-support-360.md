# Pipeline Customer Support 360°

## 1. Mục tiêu
- Cung cấp cho agent CS màn hình cập nhật mỗi phút với lịch sử đơn hàng, thanh toán, ticket, trạng thái giao hàng.
- Cho phép tìm kiếm nhanh theo email/số điện thoại (Cassandra) và truy vấn lịch sử sâu (Trino).
- Ghi nhận tương tác mới (CouchDB) và đồng bộ về lakehouse để phân tích chất lượng dịch vụ.

## 2. Kiến trúc
```
Kafka orders_cdc, payments_cdc ----\
CouchDB tickets (changes feed) ------\
PostgreSQL support_notes (CDC) -------\
Logistics status (MinIO files) -------\--> Flink -> Cassandra customer_case (API)
                                    \----> Paimon cs_timeline (analytics)
                                    \----> Kafka topic cs_notifications
```

## 3. Kết nối nguồn dữ liệu
- **CouchDB**: sử dụng `_changes` feed -> connector (Kafka Connect CouchDB source) -> topic `support.tickets`.
- **PostgreSQL**: Debezium connector `support-cdc` thu bảng `support_notes`.
- **Logistics**: file CSV upload vào MinIO -> job Flink `filesystem` connector (format CSV) đọc incremental.

## 4. Bảng Cassandra phục vụ API
```sql
CREATE TABLE cs.customer_case (
  customer_id text,
  case_id text,
  last_event_time timestamp,
  order_ids list<text>,
  payment_status text,
  ticket_status text,
  shipment_status text,
  notes text,
  PRIMARY KEY ((customer_id), last_event_time, case_id)
) WITH CLUSTERING ORDER BY (last_event_time DESC);
```
Kiến trúc token ring (theo tài liệu Cassandra) giúp phân phối khách hàng đều, RF=3 bảo đảm đọc/ghi tốc độ cao.

## 5. Bảng Paimon phân tích
```sql
CREATE TABLE cs_timeline (
  `customer_id` STRING,
  `event_type` STRING,
  `payload` MAP<STRING, STRING>,
  `event_time` TIMESTAMP(3),
  PRIMARY KEY (`customer_id`, `event_time`, `event_type`) NOT ENFORCED
) WITH (
  'bucket'='4',
  'write-mode'='change-log'
);
```

## 6. Job Flink (DataStream hoặc SQL)
- Dùng DataStream `KeyedProcessFunction` để gom sự kiện theo khách hàng và cập nhật Cassandra + Paimon.
- Sử dụng session window (`ProcessingTimeSessionWindows` theo tài liệu Flink window assigner) để đóng case sau 30 phút không tương tác.
- Pseudocode:
```scala
val tickets = env.addSource(couchDbSource)
val orders = env.addSource(kafkaOrderSource)
val payments = env.addSource(kafkaPaymentSource)

val unified = tickets.union(orders, payments)
  .keyBy(_.customerId)
  .process(new CustomerCaseProcessor())
```
- Trong `processElement`, cập nhật Cassandra bằng driver async, đồng thời emit event ghi Paimon (qua Table API). Checkpoint duy trì trong `state.checkpoints.dir` (thiết lập ở docker-compose).

## 7. Notifications
- Event `ticket escalated` -> gửi vào Kafka topic `cs_notifications`.
- Consumer (service Node.js) bắn notification Slack/email.

## 8. Dashboard & truy vấn
- UI CS đọc Cassandra (latency thấp) để hiển thị timeline.
- Trino truy vấn `cs_timeline` để phân tích SLA, thời gian phản hồi.
- Spark batch hằng tuần tạo báo cáo NPS, ghi Doris.

## 9. Observability & runbook
- Prometheus giám sát `flink_jobmanager_job_numRestarts` (alert).
- Cassandra metric `pending_tasks` tăng -> kiểm tra cluster.
- CouchDB changes feed lỗi -> xem log (Loki) `container="couchdb"`.
- Khi Flink checkpoint fail, dùng UI restore từ checkpoint cuối (theo Flink REST API docs).

## 10. Quy trình xử lý sự cố
1. Agent báo dữ liệu thiếu → kiểm tra Cassandra (CQL) và Paimon (Trino) so sánh.
2. Nếu event không vào `cs_timeline`, xem Kafka `cs_notifications` bằng CLI.
3. Validate connectors (Debezium/CouchDB) đang RUNNING qua `GET /connectors/<name>/status`.
4. Khi cần backfill, chạy job Spark đọc Paimon + logs, ghi lại Cassandra.
