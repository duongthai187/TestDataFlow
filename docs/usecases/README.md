# Use Case & Chiến lược hợp nhất dữ liệu

Tài liệu trong thư mục này mô tả các tình huống nghiệp vụ thương mại điện tử ở quy mô lớn, đi kèm phương án khai thác stack realtime-lakehouse để thống nhất dữ liệu phục vụ phân tích và vận hành.

## Danh mục
- `tinh-huong-ecommerce-phuc-tap.md`: mô tả bối cảnh doanh nghiệp, các hệ thống OLTP phân tán (SQL/NoSQL) và yêu cầu nghiệp vụ đặt ra.
- `giai-phap-thong-nhat-du-lieu.md`: thiết kế pipeline realtime/batch sử dụng Kafka, Flink, Paimon, Cassandra, Doris/Trino và Spark để đáp ứng các use case.
- `fraud-detection-pipeline.md`: quy trình phát hiện gian lận realtime với Flink CEP, Paimon và Cassandra.
- `inventory-360-pipeline.md`: hợp nhất tồn kho toàn cầu và đồng bộ với đơn hàng.
- `marketing-personalization.md`: pipeline cá nhân hoá marketing kết hợp stream hành vi và hồ sơ khách hàng.
- `finance-reconciliation.md`: đối soát tài chính đa hệ thống với Paimon và Spark batch.
- `customer-support-360.md`: cung cấp góc nhìn 360° cho trung tâm hỗ trợ khách hàng.
- `data-governance-cheatsheet.md`: hướng dẫn chuẩn hoá schema, type mapping và quản lý phiên bản (Nessie, Paimon).

Nên đọc lần lượt để nắm rõ bối cảnh trước khi đi vào chi tiết triển khai giải pháp.
