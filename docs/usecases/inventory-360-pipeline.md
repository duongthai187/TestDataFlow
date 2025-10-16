# Pipeline Inventory 360°

## 1. Mục tiêu
- Cung cấp bảng tổng hợp tồn kho realtime hợp nhất từ nhiều kho (Cassandra) và trạng thái đơn hàng (MySQL).
- Đảm bảo dashboard fulfillment cập nhật < 1 phút.
- Hỗ trợ phân tích batch dự báo nhu cầu (Spark, Doris) và chiến dịch marketing.

## 2. Luồng dữ liệu
```
Cassandra inventory_delta (CDC) --> Flink changelog source
MySQL orders_cdc (Debezium) -----> Flink windowed join ---> Paimon inventory_snapshot
                                                   \--> Cassandra inventory_projection (phục vụ API)
                                                   \--> Kafka topic inventory_alerts (optional)
```

## 3. Nguồn dữ liệu
### CDC Cassandra
- Sử dụng DataStax CDC agent hoặc change data capture topic (áp dụng trong môi trường lab: stream delta thông qua application producer ghi vào Kafka `inventory_delta`).
- Partition key trong Cassandra dựa trên `sku_id` và `warehouse_id`. Token ring (tài liệu Cassandra kiến trúc Dynamo) đảm bảo phân phối đồng đều.

### Debezium MySQL (đơn hàng)
- Reuse connector `orders-cdc` (xem pipeline fraud). Dữ liệu line-item cung cấp `quantity`, `warehouse_selection`.

## 4. Thiết kế bảng Paimon
```sql
CREATE TABLE inventory_snapshot (
  `sku_id` STRING,
  `warehouse_id` STRING,
  `available_qty` BIGINT,
  `reserved_qty` BIGINT,
  `updated_at` TIMESTAMP(3),
  PRIMARY KEY (`sku_id`, `warehouse_id`) NOT ENFORCED
) WITH (
  'bucket'='8',
  'write-mode'='change-log'
);
```
- Thiết lập `SET 'table.exec.sink.upsert-materialize' = 'NONE';` theo khuyến nghị của Apache Paimon để tránh ảnh hưởng merge engine.

## 5. Job Flink (SQL)
```sql
CREATE TEMPORARY VIEW inventory_reservations AS
SELECT o.sku_id,
       o.warehouse_id,
       SUM(o.quantity) AS reserved_qty,
       MAX(o.event_time) AS updated_at
FROM orders_cdc o
WHERE o.status IN ('CREATED','ALLOCATED')
GROUP BY o.sku_id, o.warehouse_id;

CREATE TABLE inventory_delta (
  `sku_id` STRING,
  `warehouse_id` STRING,
  `available_delta` BIGINT,
  `event_time` TIMESTAMP(3),
  WATERMARK FOR `event_time` AS `event_time` - INTERVAL '10' SECOND
) WITH (
  'connector' = 'kafka',
  'topic' = 'inventory_delta',
  'properties.bootstrap.servers' = 'kafka:9092',
  'format' = 'json'
);

INSERT INTO inventory_snapshot
SELECT d.sku_id,
       d.warehouse_id,
       SUM(d.available_delta) OVER (
         PARTITION BY d.sku_id, d.warehouse_id
         ORDER BY d.event_time
         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
       ) AS available_qty,
       COALESCE(r.reserved_qty, 0) AS reserved_qty,
       GREATEST(d.event_time, COALESCE(r.updated_at, d.event_time)) AS updated_at
FROM inventory_delta d
LEFT JOIN inventory_reservations r
  ON d.sku_id = r.sku_id AND d.warehouse_id = r.warehouse_id;
```

## 6. Sink Cassandra phục vụ API
```sql
CREATE TABLE inventory_projection (
  `sku_id` STRING,
  `warehouse_id` STRING,
  `available_qty` BIGINT,
  `reserved_qty` BIGINT,
  `updated_at` TIMESTAMP(3),
  PRIMARY KEY (`sku_id`, `warehouse_id`) NOT ENFORCED
) WITH (
  'connector' = 'cassandra',
  'keyspace' = 'supply',
  'table' = 'inventory_projection',
  'host' = 'cassandra-seed'
);

INSERT INTO inventory_projection
SELECT sku_id, warehouse_id, available_qty, reserved_qty, updated_at
FROM inventory_snapshot;
```

## 7. Batch analytics
- Spark đọc `inventory_snapshot` từ Paimon (catalog `paimon_catalog`).
- Chạy job dự báo nhu cầu: `Spark ML` -> ghi kết quả `p_forecast` vào Doris (`inventory_forecast`).
- Dashboard Trino join `inventory_snapshot` + dự báo marketing.

## 8. Alerting & tự động hoá
- Prometheus alert khi `available_qty < safety_stock` emit Kafka `inventory_alerts`.
- Khi lag Kafka cao, tăng TaskManager slots (`taskmanager.numberOfTaskSlots`) hoặc scale new TaskManager container.
- Monitor Cassandra metrics `clientrequest_latency` để phát hiện hotspot partition (căn cứ metric trong tài liệu Cassandra).

## 9. Kiểm tra chất lượng dữ liệu
- Spark batch so sánh tổng available với log kho (`warehouse_system`).
- Nessie branch `inventory-release` để kiểm thử schema; merge vào `main` khi pass QA.
