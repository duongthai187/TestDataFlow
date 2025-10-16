# Danh mục thành phần

Tài liệu này liệt kê toàn bộ dịch vụ trong `docker-compose.yml`, mô tả vai trò, cấu hình và lưu ý vận hành. Các giá trị cổng được hiển thị theo định dạng `host:container`.

## 1. Tầng streaming & tích hợp

### Apache Kafka (`kafka`)
- **Image**: `apache/kafka:latest`
- **Cổng**: `9092:9092`
- **Volume**: `kafka_data` chứa log phân vùng KRaft.
- **Vai trò**: Broker trung tâm để nhận CDC, làm message bus cho Flink, Spark và các consumer khác. Sử dụng mô hình KRaft đơn node phù hợp môi trường dev.

### Debezium Kafka Connect (`connect`)
- **Image**: `quay.io/debezium/connect:2.6`
- **Cổng**: `8083:8083`
- **Phụ thuộc**: Kafka.
- **Vai trò**: Nền tảng cấu hình connector CDC (MySQL, PostgreSQL, MongoDB...) đẩy dữ liệu vào Kafka. Có thể mở rộng thêm plugin thông qua volume nếu cần.

## 2. Nguồn dữ liệu OLTP

### MySQL (`mysql`)
- **Image**: `mysql:8.0`
- **Cổng**: `3306:3306`
- **Volume**: `mysql_data` bảo lưu dữ liệu.
- **Vai trò**: Hệ thống giao dịch mẫu; binlog được Debezium thu để tạo sự kiện CDC.

### PostgreSQL (`dataflow-postgres`)
- **Image**: `postgres:15`
- **Cổng**: `5434:5432`
- **Volume**: `postgres_data`.
- **Vai trò**: Nguồn dữ liệu quan hệ thứ cấp, phục vụ ứng dụng nội bộ hoặc metadata.

## 3. Tầng lưu trữ realtime

### Cassandra cluster (`cassandra-seed`, `cassandra-node2`, `cassandra-node3`)
- **Image**: `cassandra:4.1`
- **Cổng seed**: `9042:9042`
- **Volume**: `cassandra_data1/2/3`.
- **Vai trò**: Lưới NoSQL phân tán (3 node) phục vụ workload latency thấp. Seed node quảng bá cluster, hai node còn lại tham gia qua biến `CASSANDRA_SEEDS`.
- **Lưu ý cấu hình**: `MAX_HEAP_SIZE=512M`, `HEAP_NEWSIZE=128M` để vừa với môi trường lab.

### CouchDB (`couchdb`)
- **Image**: `couchdb:3`
- **Cổng**: `5984:5984`
- **Volume**: `couchdb_data`.
- **Vai trò**: Document store phục vụ API JSON, hỗ trợ replication đa vùng nếu mở rộng.

## 4. Tầng lakehouse & object storage

### MinIO (`minio`)
- **Image**: `minio/minio:latest`
- **Cổng**: `9000:9000`, `9001:9001`
- **Volume**: `minio_data`.
- **Vai trò**: Cung cấp giao diện S3 để lưu bảng Paimon/Iceberg, checkpoint hoặc artifact job.

### Project Nessie (`nessie`)
- **Image**: `ghcr.io/projectnessie/nessie:0.80.0`
- **Cổng**: `19120:19120`
- **Vai trò**: REST catalog quản lý phiên bản bảng (Iceberg/Paimon) cho Trino, Spark.

### Apache Paimon (Flink + thư viện JAR)
- **Triển khai**: Không có container riêng; Paimon được tích hợp thông qua các JAR trong `./flink/lib`.
- **Vai trò**: Định dạng bảng lakehouse hỗ trợ update/delete realtime. Dữ liệu lưu trên MinIO, quản lý phiên bản qua Nessie hoặc catalog nội bộ.

## 5. Tầng xử lý

### Apache Flink (`flink-jobmanager`, `flink-taskmanager`)
- **Image**: `apache/flink:1.18.1-scala_2.12`
- **Cổng JobManager**: `8088:8081` (UI), `6123:6123` (RPC)
- **Volume**: `./flink/lib` (JAR bổ sung), `flink_checkpoints` (filesystem state backend).
- **Vai trò**: Xử lý stream và batch realtime, ghi xuống Paimon, Cassandra hoặc Kafka. JobManager điều phối, TaskManager thực thi slots.
- **Điểm nổi bật**: `FLINK_PROPERTIES` thiết lập parallelism mặc định, checkpoint và địa chỉ RPC phù hợp với triển khai Docker standalone (theo hướng dẫn trong tài liệu Apache Flink).

### Apache Spark (`spark-master`, `spark-worker`)
- **Image**: `apache/spark:3.5.1`
- **Cổng Master**: `17077:7077`, `8082:8080`
- **Cổng Worker UI**: `18083:8081`
- **Vai trò**: ETL batch, xử lý lịch sử, tương tác với lakehouse thông qua connector Iceberg/Paimon.

## 6. Tầng truy vấn phân tích

### Apache Doris (`doris`)
- **Image**: `dyrnq/doris:latest`
- **Cổng**: `8030`, `8040`, `9030`
- **Volume**: `doris_data`.
- **Vai trò**: OLAP engine phục vụ báo cáo realtime. Có thể dùng routine load từ Kafka hoặc đọc bảng Paimon/Iceberg.

### Trino (`trino`)
- **Image**: `trinodb/trino:440`
- **Cổng**: `8081:8080`
- **Volume**: `./trino/catalog`, `trino_data`.
- **Vai trò**: Cổng truy vấn SQL hợp nhất, truy cập MinIO/Nessie (Iceberg, Paimon), Cassandra, Kafka... Qua các catalog định nghĩa trong `./trino/catalog`.

## 7. Phụ thuộc mạng & volume
- **Network**: `datanet` là bridge chung cho toàn bộ dịch vụ.
- **Volume**: mỗi thành phần có volume riêng nhằm tránh xung đột, thuận tiện backup.

Thông tin vận hành chi tiết (khởi động, kiểm tra) xem thêm `van-hanh.md`. Hướng dẫn pipeline cụ thể giữa Kafka → Flink → Paimon → Trino/Doris nằm trong `huong-dan-flink-paimon.md`.
