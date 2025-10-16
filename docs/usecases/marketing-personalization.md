# Pipeline cá nhân hoá marketing

## 1. Mục tiêu
- Cập nhật segment khách hàng < 5 phút để đồng bộ với hệ thống marketing automation.
- Tránh quảng bá sản phẩm hết hàng bằng cách kết hợp dữ liệu tồn kho (Paimon) và hành vi realtime.
- Tận dụng Paimon để lưu lịch sử segment versioned (qua Nessie) giúp audit chiến dịch.

## 2. Luồng dữ liệu
```
Kafka behavior_events ----\
Kafka orders_cdc -----------\
Cassandra inventory_projection -> Flink enrichment -> Paimon marketing_segments
Paimon customer_profile -----/
```

## 3. Chuẩn bị dữ liệu nền
- `customer_profile` lưu trên Paimon (batch ETL từ MySQL CRM mỗi đêm bằng Spark). Bảng có các cột RFM (Recency, Frequency, Monetary).
- `inventory_projection` realtime từ pipeline inventory 360° (Cassandra) được expose qua Flink lookup join.

## 4. Job Flink (SQL)
```sql
SET 'execution.checkpointing.interval' = '1 min';
SET 'table.exec.sink.upsert-materialize' = 'NONE';

CREATE TABLE customer_profile (
  `customer_id` BIGINT,
  `segment` STRING,
  `recency` INT,
  `frequency` INT,
  `monetary` DECIMAL(12,2),
  `lifecycle_stage` STRING,
  PRIMARY KEY (`customer_id`) NOT ENFORCED
) WITH (
  'connector' = 'paimon',
  'warehouse' = 's3://lakehouse/warehouse',
  'catalog-name' = 'paimon_catalog'
);

CREATE TABLE marketing_segments (
  `customer_id` BIGINT,
  `segment` STRING,
  `recommendation` ARRAY<STRING>,
  `score` DOUBLE,
  `updated_at` TIMESTAMP(3),
  PRIMARY KEY (`customer_id`) NOT ENFORCED
) WITH (
  'bucket'='4',
  'write-mode'='change-log'
);

CREATE TEMPORARY TABLE inventory_lookup (
  `sku_id` STRING,
  `available_qty` BIGINT,
  `reserved_qty` BIGINT,
  `updated_at` TIMESTAMP(3)
) WITH (
  'connector' = 'cassandra',
  'table' = 'inventory_projection',
  'keyspace' = 'supply',
  'host' = 'cassandra-seed'
);

INSERT INTO marketing_segments
SELECT b.user_id AS customer_id,
       CASE
         WHEN cp.segment = 'VIP' AND inv.available_qty > 10 THEN 'VIP_HIGH_INVENTORY'
         WHEN cp.recency < 7 THEN 'ACTIVE'
         ELSE 'DORMANT'
       END AS segment,
       ARRAY['sku:' || b.last_viewed_sku] AS recommendation,
       cp.frequency * 0.5 + cp.monetary * 0.1 AS score,
       CURRENT_TIMESTAMP AS updated_at
FROM behavior_events b
LEFT JOIN customer_profile FOR SYSTEM_TIME AS OF b.event_time AS cp
  ON b.user_id = cp.customer_id
LEFT JOIN inventory_lookup FOR SYSTEM_TIME AS OF b.event_time AS inv
  ON b.last_viewed_sku = inv.sku_id;
```
- Sử dụng `FOR SYSTEM_TIME AS OF` (lookup temporal join) để đảm bảo Flink lấy snapshot gần nhất. Khi sử dụng Table API, Flink nội bộ sẽ dựa trên state backend đã cấu hình (`state.checkpoints.dir` theo Flink docs).

## 5. Xuất sang downstream
- Trino: `SELECT * FROM marketing_segments` để FE marketing truy vấn.
- Kafka sink (tuỳ chọn) để đồng bộ tới hệ thống campaign: sử dụng connector Kafka `format='json'`, topic `marketing_segments_rt`.

## 6. Governance
- Mỗi khi thay đổi logic segmentation, tạo branch mới trong Nessie (`nessie branch create marketing-v2`), test, sau đó merge.
- Paimon hỗ trợ schema evolution; nếu thêm cột `channel_preference`, dùng `ALTER TABLE` và rely on `allow_non_string_to_string` khi mapping (tham khảo doc Apache Paimon).

## 7. Đo lường
- Đặt metric Flink: `flink_jobmanager_job_latency` < 300s.
- Prometheus alert nếu `marketing_segments` ghi chậm (lag Kafka > 5000).
- Spark job nightly recalculates RFM và cập nhật bảng `customer_profile`, commit tag `rfm-YYYYMMDD` trong Nessie.
