# WatchDog — Kurulum ve Kullanım Rehberi

Bu belge, WatchDog'u sıfırdan çalışır hâle getirmek için gereken adımları
içerir. Docker ile hızlı kurulum, local geliştirici ortamı ve ileri düzey
yapılandırma seçenekleri ayrı bölümlerde ele alınmıştır.

---

## Gereksinimler

| Yöntem | Gereksinim |
|--------|------------|
| Docker | Docker Engine 24+, Docker Compose v2 |
| Local | Python 3.10+, Git |

---

## 1. Docker ile Kurulum (Önerilen)

En hızlı yol. Nginx, monitor ve metrics servisleri tek komutla ayağa kalkar.

### 1.1 Ortam Dosyasını Hazırlayın

```bash
cp .env.example .env
```

`.env` dosyasını açıp en az `WATCHDOG_TARGETS_FILE` değişkenini kontrol edin.
Varsayılan değer `config/targets.yaml`'dır; kendi hedef dosyanızı eklemek
için bu değeri güncelleyin.

### 1.2 Servisleri Başlatın

```bash
docker compose up -d --build
```

Beklenen çıktı:

```
[+] Running 3/3
 ✔ Container watchdog-monitor    Started
 ✔ Container watchdog-metrics    Started
 ✔ Container watchdog-nginx      Started
```

### 1.3 Sağlık Kontrolü

```bash
curl -s http://localhost:8080/health
```

### 1.4 Dashboard

Tarayıcıda açın:

```
http://localhost:8001
```

### 1.5 Servisleri Durdurma

```bash
docker compose down
```

Veritabanını da silmek için:

```bash
docker compose down -v
```

### 1.6 Log İzleme

```bash
docker compose logs -f watchdog-monitor
docker compose logs -f watchdog-metrics
docker compose logs -f nginx
```

---

## 2. Local Kurulum (Python)

Geliştirme ortamı veya Docker olmayan makineler için.

### 2.1 Bağımlılıkları Kurun

```bash
git clone <repo-url> WEB-MONITOR
cd WEB-MONITOR

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r watchdog/requirements.txt
```

### 2.2 Ortam Değişkenlerini Tanımlayın

```bash
cp .env.example .env
# .env dosyasını düzenleyerek kendi değerlerinizi girin
```

Veya export ile doğrudan tanımlayabilirsiniz:

```bash
export WATCHDOG_TARGETS_FILE=watchdog/links.txt
export WATCHDOG_DB_PATH=watchdog.db
```

### 2.3 Yapılandırmayı Doğrulayın

```bash
python watchdog/main.py --validate-config
```

---

## 3. Genel Kullanım / Başlatma

WatchDog iki bağımsız süreçten oluşur: **monitor** ve **dashboard API**.
Bu iki sürecin aynı `WATCHDOG_DB_PATH` değerini kullanması gerekir.

### Terminal 1 — Monitor Başlatma

```bash
source .venv/bin/activate
export WATCHDOG_TARGETS_FILE=watchdog/links.txt
export WATCHDOG_DB_PATH=watchdog.db

python watchdog/main.py --monitor
```

Monitor çalışırken bu terminal açık kalır. İzleme sonuçlarını gerçek zamanlı
olarak konsola yansıtır.

### Terminal 2 — Dashboard API Başlatma

```bash
cd watchdog
source ../.venv/bin/activate
export WATCHDOG_TARGETS_FILE=/tam/yol/watchdog/links.txt
export WATCHDOG_DB_PATH=/tam/yol/watchdog.db

uvicorn src.api.app:app --host 0.0.0.0 --port 8001
```

> **Not:** `uvicorn src.api.app:app` komutu `watchdog/` dizininden
> çalıştırılmalıdır. Repo kökünden çalıştırılırsa `ModuleNotFoundError`
> alınır.

Dashboard: `http://localhost:8001`

### Temel CLI Komutları

Aşağıdaki komutlar repo kökünden çalıştırılabilir:

```bash
# Yapılandırmayı doğrula
python watchdog/main.py --validate-config

# Son 1 saatin özet raporu
python watchdog/main.py --report --last-hours 1

# Son 5 dakikanın anlık durumu
python watchdog/main.py --status --last-minutes 5

# Son 24 saatin incident listesi
python watchdog/main.py --incidents --last-hours 24

# SLO raporu
python watchdog/main.py --slo-report --last-hours 24

# Metrics sunucusunu bağımsız başlat
python watchdog/main.py --metrics-server --metrics-host 0.0.0.0 --metrics-port 9100

# Test e-postası gönder (SMTP yapılandırılmışsa)
python watchdog/main.py --send-test-email
```

---

## 4. İleri Düzey Yapılandırma

### 4.1 Ortam Değişkenleri Referansı

| Değişken | Varsayılan | Açıklama |
|----------|------------|----------|
| `WATCHDOG_DB_PATH` | `watchdog.db` | SQLite veritabanı dosyası yolu |
| `WATCHDOG_TARGETS_FILE` | `config/targets.yaml` | Hedef dosyası (YAML veya .txt) |
| `WATCHDOG_POLL_INTERVAL_SECONDS` | `30` | İzleme dalgaları arası bekleme süresi |
| `WATCHDOG_REQUEST_TIMEOUT_SECONDS` | `10` | HTTP istek zaman aşımı (poll_interval'dan küçük olmalı) |
| `WATCHDOG_MAX_CONCURRENT_REQUESTS` | `100` | Maksimum eş zamanlı istek sayısı |
| `WATCHDOG_RETENTION_DAYS` | `7` | Veritabanında saklanacak maksimum gün sayısı |
| `WATCHDOG_MAX_RETRIES` | `2` | Geçici hatada yeniden deneme sayısı |
| `WATCHDOG_ALLOW_PRIVATE_IPS` | `false` | Özel IP'lere izin ver (yalnızca güvenli iç ağlarda açın) |
| `WATCHDOG_PROFILE` | — | Profil adı; `config/targets_{PROFILE}.yaml` yükler |
| `WATCHDOG_SLACK_WEBHOOK_URL` | — | Slack webhook URL'si |
| `WATCHDOG_SMTP_HOST` | — | SMTP sunucusu |
| `WATCHDOG_SMTP_PORT` | `587` | SMTP portu |
| `WATCHDOG_SMTP_USERNAME` | — | SMTP kullanıcı adı |
| `WATCHDOG_SMTP_PASSWORD` | — | SMTP şifresi |
| `WATCHDOG_SMTP_FROM` | — | Gönderen e-posta adresi |
| `WATCHDOG_SMTP_TO` | — | Alıcı e-posta adresi |
| `WATCHDOG_MAINTENANCE_WINDOWS_FILE` | — | Bakım penceresi YAML dosyası |
| `WATCHDOG_CI_CRITICAL_SERVICES_FILE` | — | CI kritik servis listesi |
| `WATCHDOG_HEARTBEAT_PING_URL` | — | Deadman switch ping URL'si |

### 4.2 Hedef Dosyası Seçenekleri

```bash
# Düz metin URL listesi (satır başına bir URL, # ile yorum)
export WATCHDOG_TARGETS_FILE=watchdog/links.txt

# YAML hedef dosyası (per-target timeout, method, body check vb.)
export WATCHDOG_TARGETS_FILE=watchdog/config/targets.yaml

# Profil ile
export WATCHDOG_PROFILE=chaos   # → config/targets_chaos.yaml yükler
```

YAML formatında hedef tanımı:

```yaml
targets:
  - name: "Örnek Servis"
    url: "https://api.example.com/health"
    expected_status: 200
    timeout: 8
    method: GET
    latency_threshold_ms: 3000
    tls_days_before_expiry_warning: 30
    expected_json_key: "status"
    expected_json_value: "ok"
```

Düz metin formatında hedef listesi `links.txt` dosyasına YAML'a dönüştürmek için:

```bash
python watchdog/scripts/links_to_targets.py \
  --links-file watchdog/links.txt \
  --output-file watchdog/config/targets_links.yaml
```

### 4.3 Bakım Penceresi Yapılandırması

`config/maintenance_windows.yaml` örneği:

```yaml
windows:
  - url_substring: "example.com"
    start: "2026-04-01T22:00:00Z"
    end:   "2026-04-02T02:00:00Z"
```

```bash
export WATCHDOG_MAINTENANCE_WINDOWS_FILE=watchdog/config/maintenance_windows.yaml
```

Aktif bakım penceresi sırasında eşleşen URL'ler için uyarı iletilmez; ancak
kontrol kayıtları veritabanına yazılmaya devam eder.

### 4.4 SLO Yapılandırması

`config/slo.yaml` oluşturun (detay için
[`watchdog/docs/SLO_NOTLARI.md`](watchdog/docs/SLO_NOTLARI.md)):

```yaml
services:
  - name: "Ana Portal"
    url_contains: "example.com"
    target_uptime_percent: 99.5
    target_p95_ms: 2000
    window_hours: 24
```

### 4.5 CI Entegrasyonu

```bash
# Kritik servisler down ise exit code 1 döner
python watchdog/main.py --ci \
  --ci-critical-services-file watchdog/config/critical_ci_services.yaml
```

### 4.6 Prometheus Entegrasyonu

Metrics sunucusu varsayılan olarak Docker dağıtımında `watchdog-metrics`
container'ında `:9100/metrics` üzerinden sunulur. Nginx, bu endpoint'i
`/metrics` yolu altında Basic Auth ile dışarı açar.

Prometheus `scrape_configs` örneği:

```yaml
- job_name: watchdog
  static_configs:
    - targets: ["<host>:8080"]
  metrics_path: /metrics
  basic_auth:
    username: prometheus
    password: "<htpasswd içindeki şifre>"
```

---

## 5. Sık Karşılaşılan Sorunlar

| Hata | Neden | Çözüm |
|------|-------|-------|
| `ModuleNotFoundError: No module named 'src'` | `uvicorn` komutu yanlış dizinden çalıştırılıyor | `watchdog/` dizinine geçip çalıştırın |
| Dashboard açılıyor ama veri yok | Monitor çalışmıyor veya DB yolu farklı | İki sürecin aynı `WATCHDOG_DB_PATH` kullandığını doğrulayın |
| `ValidationError: WATCHDOG_REQUEST_TIMEOUT_SECONDS` | Timeout ≥ poll interval | Timeout değerini poll interval'dan küçük tutun |
| Hedef her zaman DOWN görünüyor | SSRF koruması private IP engelliyor | Hedef URL'yi kontrol edin veya iç ağda `WATCHDOG_ALLOW_PRIVATE_IPS=true` kullanın |
