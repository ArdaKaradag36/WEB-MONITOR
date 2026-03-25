# WEB-MONITOR

Self-hosted, asenkron HTTP/HTTPS izleme platformu.

---

## Proje Amacı

WEB-MONITOR, kamu ve kurumsal web servislerini merkezi olarak izlemek için
tasarlanmış hafif, self-hosted bir uptime ve performans monitörüdür. Sistem;
hedef URL'leri periyodik olarak kontrol eder, uptime/gecikme verilerini
kaydeder, kesintileri incident olarak raporlar ve operasyon ekiplerine hem
bir dashboard hem Prometheus metrikleri hem de CLI aracılığıyla görünürlük
sağlar.

Ek bir izleme servisi, veritabanı sunucusu veya bulut hesabı gerektirmez.
Tek bir Python ortamı veya Docker Compose ile çalışır.

---

## Kapsam & Hedef

**Kimler kullanabilir?**

- Sunucularını veya API'lerini takip etmek isteyen bireysel geliştiriciler
- Düşük maliyetli, kendi sunucularında çalışan bir monitor isteyen KOBİ teknik ekipleri
- CI/CD pipeline'larına SLO bazlı sağlık kontrolü eklemek isteyen DevOps ve SRE mühendisleri
- Kurumsal NOC ve sistem yönetimi ekipleri

**Ne için kullanılır?**

- Dağınık servislerin tek bir noktadan izlenmesi
- Yalnızca "up/down" değil, gecikme bazlı kalite takibi (p50/p95/p99)
- SLO tanımları ve error budget izleme
- Slack, e-posta, webhook veya PagerDuty üzerinden otomatik bildirim
- GitHub Actions veya benzer CI sistemlerine entegre sağlık kapısı

---

## Dashboard

![WatchDog NOC Dashboard](images/image1.png)

---

## Teknoloji Yığını

| Katman | Teknoloji |
|--------|-----------|
| Monitor Motoru | Python 3.10+, asyncio, aiohttp |
| API | FastAPI, Uvicorn |
| Veritabanı | SQLite (WAL modu), aiosqlite |
| Frontend | HTML + CSS + Vanilla JavaScript |
| Reverse Proxy | Nginx |
| Containerization | Docker, Docker Compose |
| CI/CD | GitHub Actions |
| Kod Kalitesi | Ruff, Pytest, Gitleaks |

---

## Mimari

```
Targets YAML / TXT
      │
      ▼
 Async Monitor Loop         ← asyncio + aiohttp + SSRF Guard
      │
      ▼
  SQLite (WAL)
      │
      ├─── FastAPI Dashboard API    → /api/status, /api/incidents, /api/slo
      ├─── Prometheus Metrics       → /metrics
      └─── CLI / TUI                → --report, --incidents, --slo-report
```

---

## Özellikler

- Asenkron monitor döngüsü — binlerce hedefte kararlı çalışma
- AIMD backpressure ile adaptif eş zamanlılık kontrolü
- SSRF koruması — DNS çözümleme ve özel IP filtresi
- Yanıt gövdesi boyutu sınırı (50 KB) — OOM koruması
- TLS sertifika süresi kontrolü — hedef bazında yapılandırılabilir
- Bakım penceresi desteği — aktif bakım sırasında uyarı baskılama
- Global circuit breaker — ağ kesintilerinde uyarı fırtınasını önler
- Retry + jitter + timeout cap — geçici hataları tolere eder
- Incident raporlama — DOWN/RESOLVED geçiş takibi
- SLO değerlendirme — PASS / PARTIAL / FAIL
- Bildirim: Slack, SMTP, Generic Webhook, PagerDuty Events v2
- Prometheus `/metrics` — p50/p95/p99, uptime, telemetri
- Docker Compose dağıtımı — Nginx Basic Auth ile korunan metrics endpoint
- CI modu — SLO'ya göre exit code; pipeline entegrasyonu

---

## Yol Haritası / Durum

| Özellik | Durum | Notlar |
|---------|-------|--------|
| Asenkron HTTP/HTTPS izleme | ✅ Tamamlandı | AIMD backpressure dahil |
| SSRF ve güvenlik kontrolleri | ✅ Tamamlandı | DNS + IP filtresi, port deny-list |
| SQLite veri katmanı | ✅ Tamamlandı | WAL modu, retry, percentile hesaplama |
| FastAPI dashboard API | ✅ Tamamlandı | /api/status, /api/incidents, /api/slo, /api/config |
| Web UI (NOC dashboard) | ✅ Tamamlandı | Vanilla JS, mobil uyumlu |
| Prometheus metrikleri | ✅ Tamamlandı | p50/p95/p99, uptime, wave telemetri |
| Incident raporlama | ✅ Tamamlandı | DOWN→UP geçiş bazlı |
| SLO raporu | ✅ Tamamlandı | PASS/PARTIAL/FAIL, API + CLI |
| TLS sertifika süresi kontrolü | ✅ Tamamlandı | Hedef bazında `tls_days_before_expiry_warning` |
| Bakım penceresi | ✅ Tamamlandı | YAML tabanlı, UTC zaman dilimi |
| Slack bildirimi | ✅ Tamamlandı | Exponential backoff ile retry |
| SMTP e-posta bildirimi | ✅ Tamamlandı | STARTTLS destekli |
| Generic webhook bildirimi | ✅ Tamamlandı | JSON payload |
| PagerDuty bildirimi | ✅ Tamamlandı | Events v2 API |
| Docker Compose dağıtımı | ✅ Tamamlandı | Multi-stage build, Nginx |
| GitHub Actions CI | ✅ Tamamlandı | Gitleaks, Ruff, Pytest, compileall |
| Profil bazlı hedef seçimi | ✅ Tamamlandı | `WATCHDOG_PROFILE` ile |
| TCP / ICMP / DNS probe | ⬜ Planlanmadı | Yalnızca HTTP/HTTPS destekleniyor |
| Çok bölgeli (multi-region) izleme | ⬜ Planlanmadı | Birden fazla deployment ile sağlanabilir |

---

## Hızlı Başlangıç

Detaylı kurulum ve yapılandırma için [`START.md`](START.md) dosyasına bakın.

```bash
cp .env.example .env
docker compose up -d --build
curl -s http://localhost:8080/health
```

Dashboard:

```
http://localhost:8001
```

---

## Güvenlik Notları

- `.env` ve `.env.*` dosyaları git tarafından izlenmez.
- SMTP, Slack, webhook kimlik bilgileri yalnızca ortam değişkenleri
  üzerinden tanımlanmalıdır.
- SSRF koruması varsayılan olarak aktiftir; özel IP adresleri engellenir.
- `/metrics` endpoint'i üretim ortamında Nginx Basic Auth veya network
  policy ile korunmalıdır.
- Ayrıntılı teknik ve operasyon notları için:
  [`watchdog/docs/OPERASYON_VE_MIMARI_NOTLARI.md`](watchdog/docs/OPERASYON_VE_MIMARI_NOTLARI.md)

---

## Proje Yapısı

```
WEB-MONITOR/
├── .github/workflows/       # CI pipeline (GitHub Actions)
├── images/                  # Belge görselleri
├── nginx/                   # Nginx yapılandırması ve htpasswd şablonu
├── scripts/                 # Yardımcı shell scriptleri
├── watchdog/
│   ├── main.py              # CLI giriş noktası
│   ├── links.txt            # Örnek düz metin URL listesi
│   ├── config/              # YAML hedef, SLO ve bakım penceresi dosyaları
│   ├── docs/                # Teknik referans belgeleri
│   ├── scripts/             # Hedef dosyası oluşturma yardımcıları
│   ├── src/
│   │   ├── api/             # FastAPI uygulaması ve dashboard
│   │   ├── core/            # Yapılandırma ve loglama
│   │   ├── infrastructure/  # Veritabanı ve notifier katmanı
│   │   ├── models/          # Pydantic veri modelleri
│   │   └── services/        # Monitor ve SLO servisleri
│   └── tests/               # Pytest test paketi
├── .env.example             # Örnek ortam değişkenleri
├── docker-compose.yml
├── Dockerfile
└── START.md                 # Kurulum ve kullanım rehberi
```
