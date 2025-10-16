# Hướng dẫn vận hành

## Khởi động & dừng hệ thống
1. **Khởi động**: từ thư mục gốc chạy `docker compose up -d`.
2. **Dừng**: `docker compose down` (giữ lại volume) hoặc `docker compose down -v` nếu muốn xoá dữ liệu.
3. **Làm mới Flink jars**: đặt file `.jar` mới vào `flink/lib/`, sau đó chạy `docker compose restart flink-jobmanager flink-taskmanager`.

## Kiểm tra trạng thái
- `docker compose ps` để xem container đang chạy.
- `docker compose logs <service>` (ví dụ `logs kafka -f`) để theo dõi log realtime.
- **Kafka**: truy cập shell với `docker compose exec kafka kafka-topics.sh --list --bootstrap-server kafka:9092`.
- **Flink Dashboard**: http://localhost:8088.
- **Spark Master UI**: http://localhost:8082.
- **Trino Web UI**: http://localhost:8081.
- **Doris FE**: http://localhost:8030.
- **MinIO Console**: http://localhost:9001 (user `admin`, pass `admin12345`).
- **CouchDB Fauxton**: http://localhost:5984/_utils (admin/admin123).

## Kiểm thử nhanh luồng CDC → Paimon
1. Tạo connector Debezium MySQL qua REST POST vào `http://localhost:8083/connectors`.
2. Kiểm tra topic xuất hiện trên Kafka.
3. Truy cập Flink UI, submit JAR pipeline (xem chi tiết ở `huong-dan-flink-paimon.md`) để sink xuống Paimon.
4. Dùng Trino CLI `docker compose exec trino trino --server http://trino:8080` truy vấn bảng Paimon.

## Giám sát hiệu năng & tài nguyên
- Theo dõi CPU/Memory container qua `docker stats`.
- Cassandra: `docker compose exec cassandra-seed nodetool status` để chắc chắn 3 node trạng thái `UN`.
- Flink: bật checkpoint interval trong job để đảm bảo khả năng phục hồi.

## Sao lưu & phục hồi
- Sao lưu volume quan trọng (`minio_data`, `cassandra_data*`, `postgres_data`, `kafka_data`) bằng `docker run --rm -v <volume>:/data busybox tar czf - /data > backup.tgz`.
- Khi phục hồi, dừng container liên quan rồi giải nén ngược vào volume.

## Xử lý sự cố phổ biến
- **Port conflict**: đổi cổng host trong `docker-compose.yml` nếu bị chiếm dụng.
- **Cassandra node down**: kiểm tra log xem memory hoặc thời gian khởi động; điều chỉnh `MAX_HEAP_SIZE` hoặc tăng tài nguyên host.
- **Flink không thấy JAR**: đảm bảo file nằm trong `flink/lib` và tên không chứa khoảng trắng.
- **Trino catalog lỗi**: xác thực cấu hình trong `trino/catalog/*.properties` phù hợp thông tin MinIO/Nessie.
