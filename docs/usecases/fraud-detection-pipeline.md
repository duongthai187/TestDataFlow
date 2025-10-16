# Pipeline phát hiện gian lận realtime

## 1. Mục tiêu & SLO
- Phát hiện giao dịch nghi vấn trong vòng **< 2 phút** kể từ khi đơn hàng tạo.
- Kết hợp dữ liệu đa hệ thống: MySQL (đơn hàng), PostgreSQL (thanh toán), Kafka (hành vi), Cassandra (histories địa chỉ), CouchDB (review).
- Lưu trạng thái và quyết định vào Cassandra để phục vụ API realtime, đồng thời ghi bảng Paimon `fraud_signals` cho phân tích và audit.

## 2. Sơ đồ luồng dữ liệu
```
MySQL binlog --> Debezium --> Kafka topic orders_cdc ---\
PostgreSQL WAL --> Debezium --> Kafka topic payments_cdc ----> Flink CEP ----> Cassandra keyspace fraud
Clickstream (Kafka raw) ------------------------------------/                         |
                                                                                      +--> Paimon table fraud_signals
```
- Kafka chạy ở chế độ KRaft một node (như hướng dẫn quickstart của Apache Kafka) với topic compact dành cho output (ví dụ `fraud_alerts`).
- Flink nhận dữ liệu qua JobManager (REST 8081/8088) và phân phối cho TaskManager theo parallelism đã cấu hình trong `docker-compose.yml`.

## 3. Thiết lập nguồn dữ liệu
### Debezium connector MySQL (đơn hàng)
```json
POST http://localhost:8083/connectors
{
  "name": "orders-cdc",
  "config": {
    "connector.class": "io.debezium.connector.mysql.MySqlConnector",
    "database.hostname": "mysql",
    "database.port": "3306",
    "database.user": "debezium",
    "database.password": "dbz",
    "database.server.id": "5401",
    "database.server.name": "commerce",
    "table.include.list": "oltp.orders,oltp.order_items",
    "database.history.kafka.bootstrap.servers": "kafka:9092",
    "database.history.kafka.topic": "schema-changes.orders",
    "include.schema.changes": "false",
    "snapshot.mode": "initial"
  }
}
```

### Debezium connector PostgreSQL (thanh toán)
```json
{
  "name": "payments-cdc",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "postgres",
    "database.port": "5432",
    "database.user": "debezium",
    "database.password": "dbz",
    "database.dbname": "appdb",
    "schema.include.list": "public",
    "table.include.list": "public.payments,public.chargebacks",
    "plugin.name": "pgoutput"
  }
}
```

### Topic hành vi
Tạo qua Kafka CLI (tham khảo quickstart của Apache Kafka):
```bash
bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --topic behavior_events --partitions 6 --replication-factor 1
```

## 4. Thiết kế job Flink
### a. Logic CEP
- Sử dụng Flink DataStream API với window session để gom sự kiện liên quan. Các window assigner như `TumblingEventTimeWindows` và `ProcessingTimeSessionWindows` được mô tả trong tài liệu `pyflink.datastream.window` của Apache Flink.
- Pipeline tổng quan:
  1. Stream đơn hàng và thanh toán được key theo `user_id`.
  2. Hành vi clickstream (topic `behavior_events`) cũng key theo `user_id`.
  3. Sử dụng CEP pattern: `orderCreated -> paymentAttempt -> multiple address change -> high risk behavior`.
  4. Kết quả pattern phát cảnh báo.

### b. Khai báo trong Flink SQL (ví dụ SQL Client)
```sql
SET 'execution.checkpointing.interval' = '30 s';
SET 'table.exec.sink.upsert-materialize' = 'NONE';  -- Khuyến nghị từ tài liệu Apache Paimon khi ghi bảng có PK

CREATE TABLE orders_cdc (
  `order_id` BIGINT,
  `user_id` BIGINT,
  `total_amount` DECIMAL(12,2),
  `shipping_address_id` BIGINT,
  `event_time` TIMESTAMP(3),
  WATERMARK FOR `event_time` AS `event_time` - INTERVAL '5' SECOND
) WITH (
  'connector' = 'kafka',
  'topic' = 'commerce.oltp.orders',
  'properties.bootstrap.servers' = 'kafka:9092',
  'format' = 'json'
);

CREATE TABLE payments_cdc (
  `order_id` BIGINT,
  `status` STRING,
  `attempt_count` INT,
  `payment_method` STRING,
  `event_time` TIMESTAMP(3),
  WATERMARK FOR `event_time` AS `event_time` - INTERVAL '5' SECOND
) WITH (
  'connector' = 'kafka',
  'topic' = 'commerce.payments',
  'properties.bootstrap.servers' = 'kafka:9092',
  'format' = 'json'
);

CREATE TABLE behavior_events (
  `user_id` BIGINT,
  `event_type` STRING,
  `metadata` MAP<STRING, STRING>,
  `event_time` TIMESTAMP(3),
  WATERMARK FOR `event_time` AS `event_time` - INTERVAL '10' SECOND
) WITH (
  'connector' = 'kafka',
  'topic' = 'behavior_events',
  'properties.bootstrap.servers' = 'kafka:9092',
  'format' = 'json'
);
```
Job CEP phức tạp thường triển khai ở DataStream API/SQL `MATCH_RECOGNIZE`. Ví dụ:
```sql
CREATE TABLE fraud_signals (
  `order_id` BIGINT,
  `user_id` BIGINT,
  `risk_score` DOUBLE,
  `reasons` ARRAY<STRING>,
  `decision_time` TIMESTAMP(3),
  PRIMARY KEY (`order_id`) NOT ENFORCED
) WITH ('bucket'='4','write-mode'='change-log');

INSERT INTO fraud_signals
SELECT *
FROM orders_cdc
MATCH_RECOGNIZE (
  PARTITION BY user_id
  ORDER BY event_time
  MEASURES
    FINAL SUM(payments_cdc.attempt_count) AS risk_score,
    FINAL ARRAY['multiple_payment_attempt','behavior_alert'] AS reasons,
    FINAL LAST(event_time) AS decision_time
  PATTERN (o p b)
  WITHIN INTERVAL '2' MINUTE
  DEFINE
    p AS payments_cdc.status = 'DECLINED',
    b AS behavior_events.event_type IN ('address_change','ip_change')
) mr;
```

### c. Ghi xuống Cassandra
Flink DataStream có thể sử dụng `CassandraSink.addSink`. Kiểu partition được hưởng lợi từ kiến trúc token ring của Cassandra (tài liệu "dynamo" mô tả cách hash key và nhân bản RF=3), đảm bảo dữ liệu phân tán đồng đều.

Pseudo code (Scala):
```scala
val sink = CassandraSink.addSink(alertStream)
  .setHost("cassandra-seed", 9042)
  .build()
```

## 5. Xử lý kết quả & tích hợp downstream
- **Realtime API** đọc từ bảng Cassandra `fraud.alerts` (RF=3, partition theo `user_id`). Ví dụ CQL:
  ```sql
  CREATE TABLE fraud.alerts (
    user_id bigint,
    decision_time timestamp,
    order_id bigint,
    risk_score double,
    reasons list<text>,
    PRIMARY KEY ((user_id), decision_time, order_id)
  ) WITH default_time_to_live = 86400;
  ```
- **Paimon** lưu tập tin trong MinIO (`s3://lakehouse/warehouse`), version bởi Nessie giúp truy xuất audit trail. Tùy chọn type mapping (`char-to-string`, `tinyint1-not-bool`) từ tài liệu Paimon đảm bảo tương thích schema.
- **Doris/Trino** truy vấn `fraud_signals` để dashboard.

## 6. Kiểm thử & triển khai
1. Gửi sự kiện thử vào Kafka topics.
2. Quan sát Flink UI (8088) để đảm bảo job chạy, checkpoint status `COMPLETED`.
3. Kiểm tra Cassandra qua `nodetool status` để chắc chắn 3 node ở trạng thái `UN`.
4. Truy vấn Paimon bằng Trino:
   ```sql
   SELECT * FROM paimon.default.fraud_signals ORDER BY decision_time DESC LIMIT 20;
   ```
5. Thiết lập alert Prometheus `FlinkJobRestarting` để phát hiện job restart bất thường.

## 7. Mở rộng
- Thêm mô hình Machine Learning: Spark đọc `fraud_signals`, huấn luyện và xuất threshold back vào Paimon để Flink tra cứu.
- Bật Vector Search trên Cassandra (theo tài liệu Cassandra vector search) để lưu embedding hành vi người dùng.
- Dùng Kafka topic compact cho `fraud_policy` (configuration) và Flink broadcast state để tải chính sách mới realtime.
