# Tình huống thương mại điện tử phức tạp

## 1. Bối cảnh doanh nghiệp
Một tập đoàn thương mại điện tử hoạt động tại Bắc Mỹ, Châu Âu và Đông Nam Á vận hành theo mô hình microservices. Mỗi vùng có trung tâm dữ liệu riêng, đồng bộ thông qua các cơ chế eventual consistency. Phần mềm được triển khai đa ngôn ngữ (Java, Python, Node.js) với cơ sở dữ liệu hỗn hợp nhằm tối ưu cho từng workload. Mục tiêu chiến lược:
- Đảm bảo trải nghiệm khách hàng realtime (giá, tồn kho, giao hàng) bất kể khu vực.
- Hỗ trợ phân tích vận hành và marketing đa kênh với độ trễ dưới 5 phút.
- Cung cấp nền tảng governance để đội ngũ dữ liệu kiểm soát phiên bản, truy xuất nguồn gốc và tuân thủ GDPR/PCI-DSS.

## 2. Bức tranh hệ thống OLTP hiện tại
| Miền nghiệp vụ | Công nghệ chính | Mô tả | Đặc tính | Vấn đề phát sinh |
| --- | --- | --- | --- | --- |
| Đặt hàng & giỏ hàng | MySQL 8 (master-replica) theo vùng | Lưu giao dịch đặt hàng, trạng thái line-item | ACID mạnh, binlog bật ROW để CDC | Replica mỗi vùng → khó hợp nhất cross-region |
| Thanh toán & sổ cái | PostgreSQL 15 | Ghi nhận trạng thái thanh toán, đối soát PSP | Transaction chi tiết, nhiều bảng liên kết | Batch reconciliation chậm, khó đồng bộ với đơn hàng realtime |
| Quản lý tồn kho | Cassandra 4.1 (3 node/region) | Ghi giảm tồn, dự trữ, hold tạm thời | Latency thấp, TTL, mô hình wide-column | Khó join với dữ liệu giá/khuyến mãi khi phân tích |
| Nội dung sản phẩm & review | CouchDB 3 | Lưu mô tả đa ngôn ngữ, review JSON | API REST, replication đa vùng | Không đồng nhất với catalog SQL, khó báo cáo |
| Sự kiện hành vi khách hàng | Kafka (event bus khác) | Clickstream, view, add-to-cart | Khối lượng lớn, schema avro | Tách biệt với pipeline phân tích trung tâm |
| Dịch vụ khách hàng | PostgreSQL + bảng tạm trên MinIO | Ticket, lịch sử tương tác | Latency trung bình, workload batch | Thiếu dữ liệu realtime từ các hệ thống khác |

Các hệ thống giao tiếp qua REST/gRPC và message queue, tuy nhiên dữ liệu phân tán khiến việc phân tích end-to-end kéo dài hàng giờ. Đội ngũ data science phải chạy nhiều job thủ công để ghép dữ liệu, gây chậm trễ trong phản ứng.

## 3. Nhu cầu nghiệp vụ nổi bật
1. **Phát hiện gian lận realtime**: Trong vòng 2 phút kể từ khi đơn hàng tạo, hệ thống phải đánh giá rủi ro dựa trên lịch sử thanh toán (PostgreSQL), tần suất đổi địa chỉ (Cassandra) và hành vi gần đây (Kafka).
2. **Đồng bộ tồn kho toàn cầu**: Trung tâm fulfillment cần dashboard hợp nhất tồn kho kho hàng trên Cassandra và trạng thái đơn hàng MySQL để chuyển hướng vận chuyển.
3. **Cá nhân hóa marketing**: Bộ phận marketing cần feed dữ liệu gần realtime (<=5 phút) để cập nhật segmentation trên Trino/Doris, kết hợp tồn kho để tránh quảng cáo sản phẩm hết hàng.
4. **Đối soát tài chính cuối ngày**: Finance yêu cầu báo cáo chính xác giữa MySQL (đơn hàng), PostgreSQL (thanh toán), và log giao nhận (ghi lên MinIO) để nộp kiểm toán.
5. **360° Customer Support**: Nhân viên CS cần màn hình tổng hợp lịch sử đơn hàng, thanh toán, khiếu nại và trạng thái vận chuyển cập nhật từng phút.

## 4. Thách thức kỹ thuật
- **Schema khác biệt**: SQL dùng mô hình chuẩn hóa, Cassandra/CouchDB dạng lược đồ linh hoạt → khó join nếu không có layer trung gian.
- **Đồng bộ vùng**: Replica MySQL và Cassandra theo vùng dẫn tới latency khi gom dữ liệu toàn cầu.
- **Batch vs realtime**: Một số phân tích cần batch (tài chính), số khác cần streaming (fraud, marketing). Đội ngũ phải duy trì 2 hạ tầng song song.
- **Governance**: Thay đổi schema từ đội ngũ ứng dụng không được thông báo trước → job ETL fail mà không ai phát hiện kịp thời.
- **Khả năng mở rộng**: Mùa lễ hội khiến lưu lượng tăng gấp 10 lần, pipeline phải auto-scale và duy trì SLA.

Tài liệu tiếp theo mô tả cách khai thác stack hiện hữu trong `docker-compose.yml` để thống nhất dữ liệu, giải quyết đồng thời yêu cầu realtime lẫn batch.
