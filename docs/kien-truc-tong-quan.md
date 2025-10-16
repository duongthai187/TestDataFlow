# Kiến trúc tổng quan

## Mục tiêu
- Thu nhận thay đổi dữ liệu theo thời gian thực (CDC) từ hệ thống OLTP và các nguồn phân tán.
- Gom luồng dữ liệu vào Kafka để tách biệt nguồn và đích, tối ưu hoá khả năng mở rộng.
- Hợp nhất realtime store (Cassandra/CouchDB) với lakehouse (Paimon trên MinIO + Nessie + Trino/Doris) nhằm phục vụ cả workload giao dịch lẫn phân tích.
- Cung cấp công cụ xử lý song song (Flink, Spark) cho nhu cầu stream/batch ETL và tích hợp các data product.

## Luồng dữ liệu chuẩn
1. **MySQL** ghi nhận giao dịch OLTP.
2. **Debezium Kafka Connect** thu CDC binlog và đẩy sự kiện vào **Kafka**.
3. **Flink** đọc topic Kafka, xử lý realtime và ghi xuống **Apache Paimon** (lake table) hoặc cập nhật **Cassandra/CouchDB** cho nhu cầu latency thấp.
4. **Apache Paimon** lưu trữ dữ liệu cập nhật liên tục trên MinIO (S3) với quản lý phiên bản qua Nessie.
5. **Doris** và **Trino** truy vấn lakehouse (qua catalog Nessie/Iceberg hoặc Paimon) để phục vụ báo cáo gần realtime.
6. **Spark** chạy batch ETL, đồng bộ dữ liệu lịch sử, hoặc chuyển đổi sang các định dạng khác trong lakehouse.
7. **PostgreSQL** đóng vai trò RDBMS bổ sung cho các ứng dụng/metadata.

## Pattern vận hành chính
- **Realtime Truth Store**: Kafka + Flink + Cassandra cho phép đọc dữ liệu gần như ngay lập tức để phục vụ API thời gian thực.
- **Serving Layer**: Paimon (qua Trino/Doris) cung cấp dữ liệu chuẩn hoá cho báo cáo BI và machine learning feature store.
- **Governance & Lineage**: Nessie quản lý phiên bản bảng Iceberg/Paimon, cho phép audit, rollback và phối hợp giữa các team dữ liệu.

## Kiến trúc triển khai Docker Compose
- Tất cả container nằm trên mạng bridge `datanet` để dịch vụ có thể truy cập nhau thông qua hostname nội bộ.
- Volume đặt tên riêng cho từng thành phần để đảm bảo dữ liệu bền vững giữa các lần khởi động.
- Flink sử dụng `./flink/lib` nhằm nạp các connector ngoài (ví dụ `paimon-flink-1.18-0.8.0.jar`, `paimon-flink-action-0.8.0.jar`).

Sơ đồ chi tiết cho từng dịch vụ và cấu hình cụ thể được trình bày trong `thanh-phan.md`, trong khi `huong-dan-flink-paimon.md` hướng dẫn triển khai pipeline mẫu.
Các tình huống nghiệp vụ phức tạp và giải pháp cụ thể được mô tả trong thư mục `usecases/`, còn chiến lược giám sát, phản ứng sự cố nằm tại `monitoring/`.
