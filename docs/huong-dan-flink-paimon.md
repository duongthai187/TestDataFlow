# Hướng dẫn Flink + Paimon

Tài liệu này trình bày quy trình thiết lập pipeline realtime từ Kafka sang Apache Paimon bằng Apache Flink. Các hướng dẫn bám sát tài liệu chính thức của Apache Flink và Apache Paimon.

## 1. Chuẩn bị
- Thư mục `flink/lib/` đã chứa các JAR:
  - `paimon-flink-1.18-0.8.0.jar` (connector chính cho Flink 1.18).
  - `paimon-flink-action-0.8.0.jar` (hỗ trợ job đồng bộ/công cụ bảo trì).
- MinIO cung cấp endpoint S3 giả lập (`http://minio:9000`) và Nessie làm catalog (endpoint `http://nessie:19120`).
- Flink sử dụng filesystem checkpoint `file:///opt/flink/checkpoints` giúp job khôi phục trạng thái nếu restart.

## 2. Khởi tạo bucket & credential MinIO
```powershell
# tạo bucket "lakehouse" nếu chưa có
docker compose exec minio mc alias set local http://minio:9000 admin admin12345
docker compose exec minio mc mb -p local/lakehouse
```

## 3. Tạo catalog Paimon trong Flink SQL Client
```bash
docker compose exec flink-jobmanager ./bin/sql-client.sh
```
Trong SQL Client, khai báo catalog sử dụng MinIO + Nessie:
```sql
CREATE CATALOG paimon_catalog WITH (
  'type' = 'paimon',
  'metastore' = 'nessie',
  'nessie.uri' = 'http://nessie:19120/api/v1',
  'nessie.ref' = 'main',
  'warehouse' = 's3://lakehouse/warehouse',
  's3.endpoint' = 'http://minio:9000',
  's3.access-key' = 'admin',
  's3.secret-key' = 'admin12345',
  's3.path.style.access' = 'true'
);

USE CATALOG paimon_catalog;
```
> Ghi chú: Paimon hỗ trợ nhiều tuỳ chọn ánh xạ kiểu dữ liệu CDC. Khi đồng bộ từ MySQL qua Debezium, có thể bật các option như `--type_mapping char-to-string` hoặc `--type_mapping tinyint1-not-bool` (theo hướng dẫn trong tài liệu Paimon CDC) khi chạy job action để xử lý compatibility.

## 4. Định nghĩa bảng nguồn Kafka và bảng đích Paimon
```sql
CREATE TABLE kafka_orders (
  `id` BIGINT,
  `status` STRING,
  `total_amount` DECIMAL(12,2),
  `updated_at` TIMESTAMP(3),
  WATERMARK FOR `updated_at` AS `updated_at` - INTERVAL '5' SECOND
) WITH (
  'connector' = 'kafka',
  'topic' = 'orders',
  'properties.bootstrap.servers' = 'kafka:9092',
  'scan.startup.mode' = 'latest-offset',
  'format' = 'json'
);

CREATE TABLE lakehouse_orders (
  `id` BIGINT,
  `status` STRING,
  `total_amount` DECIMAL(12,2),
  `updated_at` TIMESTAMP(3),
  PRIMARY KEY (`id`) NOT ENFORCED
) WITH (
  'bucket' = '4',
  'write-mode' = 'change-log'
);
```

## 5. Chạy job Flink
```sql
INSERT INTO lakehouse_orders
SELECT id, status, total_amount, updated_at
FROM kafka_orders;
```
Job sẽ xuất hiện trong Flink Dashboard tại http://localhost:8088. Checkpoint được lưu trong volume `flink_checkpoints`.

## 6. Truy vấn dữ liệu qua Trino hoặc Doris
Ví dụ với Trino CLI:
```bash
docker compose exec trino trino --server http://trino:8080 --catalog paimon --schema default <<'SQL'
SELECT id, status, total_amount, updated_at
FROM lakehouse_orders
ORDER BY updated_at DESC
LIMIT 20;
SQL
```

## 7. Công cụ đồng bộ CDC toàn bộ database
Apache Paimon cung cấp action đồng bộ Debezium/MySQL toàn khối. Ví dụ (thực thi ngoài SQL Client):
```bash
docker compose exec flink-jobmanager ./bin/flink run \
  /opt/flink/usrlib/paimon-flink-action-0.8.0.jar \
  cdc-sync \
  --warehouse s3://lakehouse/warehouse \
  --metastore nessie \
  --nessie-uri http://nessie:19120/api/v1 \
  --database app \
  --table orders \
  --kafka-bootstrap-servers kafka:9092 \
  --topic-prefix app_ \
  --type_mapping char-to-string
```
Tham số `--type_mapping char-to-string` giúp map thống nhất `CHAR/VARCHAR` sang `STRING` theo gợi ý trong tài liệu chính thức của Apache Paimon.

## 8. Best practice
- Đặt khoảng checkpoint trong job (`SET 'execution.checkpointing.interval' = '30 s';`) để đảm bảo khôi phục.
- Sử dụng `SET 'table.exec.sink.upsert-materialize' = 'NONE';` khi ghi vào bảng Paimon có khoá chính nhằm tránh ảnh hưởng merge engine.
- Theo dõi slot sử dụng tại Flink UI; tăng `taskmanager.numberOfTaskSlots` hoặc bổ sung TaskManager nếu job bão hoà.

Hoàn tất các bước trên sẽ tạo pipeline realtime chuẩn giữa Kafka và Paimon, đồng thời mở đường cho việc phục vụ dữ liệu phân tích qua Trino/Doris và truy cập realtime qua Cassandra.
