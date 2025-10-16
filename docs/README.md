# Hệ thống Dataflow Realtime-Lakehouse

Bộ tài liệu này mô tả kiến trúc và cách vận hành stack dữ liệu realtime + lakehouse được định nghĩa trong `docker-compose.yml`. Hệ thống kết hợp các thành phần của Apache Foundation và phần mềm nguồn mở để xử lý dòng dữ liệu CDC, lưu trữ phân tán, truy vấn phân tích và phục vụ báo cáo.

## Cấu trúc tài liệu
- `kien-truc-tong-quan.md`: mô tả mục tiêu kiến trúc, luồng dữ liệu chính và các pattern vận hành.
- `thanh-phan.md`: chi tiết từng dịch vụ trong docker-compose, bao gồm vai trò, cấu hình cổng, volume và phụ thuộc.
- `van-hanh.md`: hướng dẫn chạy, kiểm tra trạng thái và khắc phục sự cố cơ bản.
- `huong-dan-flink-paimon.md`: hướng dẫn triển khai Flink + Paimon cho dòng dữ liệu realtime và lakehouse.
- `usecases/`: tập hợp tình huống nghiệp vụ phức tạp, mô hình dữ liệu và chiến lược thống nhất phân tích.
- `monitoring/`: chiến lược quan sát, cảnh báo và quy trình ứng cứu sự cố.

## Khung sử dụng
1. Chuẩn bị Docker và Docker Compose trên máy chủ (Windows hỗ trợ thông qua WSL2 hoặc Docker Desktop).
2. Sao chép repo này và chạy `docker compose up -d` từ thư mục gốc.
3. Tham khảo các tệp trong thư mục `docs/` để nắm luồng dữ liệu, cấu hình chi tiết và các thao tác kiểm thử.

Việc duy trì tài liệu theo chuẩn giúp đội ngũ phát triển, vận hành và dữ liệu dễ dàng hiểu vai trò của từng thành phần, đảm bảo khả năng mở rộng cũng như tuân thủ các SLO về độ trễ, độ tin cậy và chất lượng dữ liệu.
