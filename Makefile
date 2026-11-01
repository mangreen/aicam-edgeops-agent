# Host 只需要 Docker 與瀏覽器（macOS 內建 pip 是 Python 2.7，不要用）
A=http://localhost:8000
.env:     ; cp .env.example .env
up: .env  ; docker compose up -d --build && echo "UI: $(A)"
down:     ; docker compose down
demo:     ; open $(A) || true
fault-A:  ; curl -s -X POST "$(A)/api/demo/fault/inference_stalled?lane=1"
fault-B:  ; curl -s -X POST "$(A)/api/demo/fault/camera_no_signal?lane=1"
fault-E:  ; curl -s -X POST "$(A)/api/demo/fault/bad_config?lane=1"
reset:    ; curl -s -X POST "$(A)/api/demo/reset"
lint:     ; docker build -q -f tests/Dockerfile -t aicam-test . && docker run --rm -v "$(CURDIR)":/w aicam-test ruff check .
logs:     ; docker compose logs -f --tail=50
test:     ; docker build -q -f tests/Dockerfile -t aicam-test . && docker run --rm -v "$(CURDIR)":/w aicam-test
