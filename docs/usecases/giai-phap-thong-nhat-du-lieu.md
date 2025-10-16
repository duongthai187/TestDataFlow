# Giải pháp thống nhất dữ liệu & phân tích

## 1. Mục tiêu thiết kế
- Hợp nhất dữ liệu từ nhiều hệ thống OLTP (MySQL, PostgreSQL, Cassandra, CouchDB) mà không phá vỡ kiến trúc microservices.
- Cung cấp cả hai luồng xử lý realtime (SLA < 2 phút) và batch (đối soát cuối ngày) trên cùng nền tảng.
- Đảm bảo khả năng truy xuất nguồn gốc, quản trị schema và rollback phiên bản.
- Giảm tải cho hệ thống giao dịch bằng cách tách layer phân tích trên Kafka + Flink + Paimon, tuân thủ khuyến nghị kiến trúc của Apache Flink về việc sử dụng JobManager điều phối và TaskManager thực thi.

## 2. Kiến trúc logic
```
Nguồn OLTP → Debezium Connect → Kafka → Flink (stream) → Paimon (lakehouse) → Trino/Doris/Spark
                                       ↘ Cassandra/CouchDB (serving realtime)
                                      ↘ MinIO (checkpoint, snapshot)
```
- **Kafka** đóng vai trò trung tâm tách rời giữa nguồn và đích. Việc cấu hình KRaft đơn giản hóa HA ở môi trường phát triển, song vẫn giữ được khả năng scale producer/consumer.
- **Debezium Connect** chuyển đổi binlog MySQL/PostgreSQL thành sự kiện JSON/Avro, đảm bảo toàn vẹn dữ liệu.
- **Flink** chạy ở chế độ session cluster: JobManager (REST 8081/8088) nhận job từ CLI/UI, TaskManager thi hành xử lý song song. `FLINK_PROPERTIES` được cấu hình checkpoint filesystem (`state.checkpoints.dir`) nhằm bảo vệ trạng thái theo hướng dẫn deployment của Apache Flink.
- **Apache Paimon** lưu trữ bảng lakehouse cập nhật realtime trên MinIO, kết hợp Nessie để versioning, hỗ trợ `CHANGELOG` và `PRIMARY KEY` table cho các use case cần upsert.
- **Trino/Doris** khai thác dữ liệu phục vụ BI, marketing; **Spark** hỗ trợ batch ETL phức tạp hoặc ML pipeline.
- **Cassandra/CouchDB** nhận dữ liệu realtime từ Flink khi cần phục vụ ứng dụng API latency thấp (ví dụ màn hình customer support).

## 3. Bản đồ use case → pipeline
| Use case | Luồng dữ liệu realtime | Luồng batch/ngoại tuyến | Data sản phẩm đầu ra |
| --- | --- | --- | --- |
| Fraud detection | Kafka topic `orders`, `payments`, `behavior` → Flink CEP → bảng Paimon `fraud_signals` + cảnh báo Kafka `fraud_alerts` | Spark batch tái huấn luyện mô hình/threshold mỗi đêm | API cảnh báo realtime, dashboard risk trên Trino |
| Inventory 360° | Kafka CDC từ MySQL (đơn hàng) + stream Cassandra (inventory delta) → Flink join + stateful aggregation → Cassandra `inventory_projection` & Paimon `inventory_snapshot` | Spark tạo forecast demand, ghi Doris để báo cáo | Bảng realtime cho OMS, bảng phân tích cho Supply Chain |
| Marketing personalization | Kafka stream hành vi → Flink enrichment với Paimon `customer_profile` → ghi Paimon `marketing_segments` | Job batch Spark tính RFM/CLV, cập nhật Paimon | Trino query bảng segment, xuất sang công cụ marketing |
| Finance reconciliation | Debezium MySQL + PostgreSQL → Flink sink Paimon `finance_fact` (đảm bảo schema type mapping `char-to-string`, `tinyint1-not-bool` theo hướng dẫn Apache Paimon) | Spark/Doris tạo báo cáo EoD, lưu PDF/Excel | Báo cáo hợp nhất, audit trail (Nessie commit hash) |
| Customer Support 360° | Flink stream combine order, payment, ticket → ghi CouchDB view `customer_case` và cache Cassandra | Batch Spark đồng bộ log giao nhận vào Paimon, update CS dashboard | UI realtime cho agent, truy vấn lịch sử trên Trino |

## 4. Chiến lược realtime vs batch
- **Realtime**: mỗi use case gắn với job Flink riêng (hoặc `Flink SQL` thông qua `sql-client`). Checkpoint interval 30s và chế độ `exactly-once` (sử dụng sink Paimon/Cassandra). Flink Dashboard (8088) theo dõi latency, backpressure.
- **Batch**: Spark đọc dữ liệu Paimon (hoặc Iceberg) định kỳ. Trino/Doris dùng để sinh báo cáo hoặc cung cấp cho đội marketing. Lịch xử lý quản lý bằng Airflow/Argo (ngoài phạm vi compose nhưng được khuyến nghị).

## 5. Quản trị dữ liệu & versioning
- **Nessie**: mỗi pipeline commit thành branch/tag (ví dụ `finance/daily-yyyymmdd`). Cho phép review schema, rollback khi phát hiện lỗi.
- **Paimon Schema Evolution**: dùng các tùy chọn type mapping từ tài liệu chính thức (ví dụ `--type_mapping char-to-string`, `allow_non_string_to_string`) để đảm bảo đồng bộ schema giữa MySQL và lakehouse.
- **Catalog chuẩn hoá**: Catalog Trino/Paimon đặt theo domain `commerce.orders`, `commerce.payments` để dễ truy cập.

## 6. Khả năng mở rộng & độ bền
- Thêm TaskManager (scale out) khi backlog Kafka tăng, sử dụng biến môi trường `taskmanager.numberOfTaskSlots`.
- Cassandra cluster có thể mở rộng node 4/5 bằng cách bổ sung service trong compose với `CASSANDRA_SEEDS` trỏ seed hiện có.
- Sử dụng MinIO erasure coding (nâng cấp cấu hình) khi cần đảm bảo độ bền cao.
- Tận dụng Kafka partition scaling để song song hóa job Flink (đồng bộ `parallelism.default`).

## 7. Quy trình triển khai use case mới
1. Định nghĩa topic Kafka và connector Debezium cần thiết.
2. Thiết kế schema Paimon, commit branch mới trên Nessie.
3. Viết Flink SQL/Datastream job, nạp JAR vào `flink/lib`, deploy qua UI hoặc CLI.
4. Thiết lập dashboard Trino/Doris hoặc API phục vụ.
5. Cập nhật tài liệu SLO, biểu đồ dữ liệu và quy trình monitoring (xem `monitoring/chien-luoc-observability.md`).

Thiết kế này cho phép đội ngũ đáp ứng đồng thời yêu cầu realtime và batch mà không phải xây dựng hạ tầng riêng biệt, đồng thời tận dụng các khuyến nghị chính thức từ Apache Flink và Apache Paimon về quản lý phiên bản, schema và vận hành cluster.
