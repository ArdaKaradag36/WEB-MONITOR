# WEB-MONITOR (WatchDog)

NVI bünyesinde staj sürecimde geliştirdiğim bu proje, kamu ve özel web servislerini merkezi olarak izlemek için tasarlanmış self-hosted bir web monitor uygulamasıdır. Sistem; hedef URL'leri periyodik olarak kontrol eder, uptime/latency verilerini kaydeder, kesinti anlarını incident olarak raporlar ve hem API hem dashboard hem de Prometheus metrikleri üzerinden operasyon ekiplerine görünürlük sağlar.

## Portföy Özeti

Bu projeyi tek başıma, üretim mantığına yakın bir yaklaşımla geliştirdim: asenkron izleme motoru, SQLite tabanlı veri katmanı, FastAPI ile dashboard API'si, Docker tabanlı çalıştırma ve GitHub Actions ile kalite kontrol adımlarını tek bir sistemde topladım. Amacım, kurum içi veya internet üzeri kritik servislerin kesinti ve performans problemlerini erken tespit edebilen, düşük maliyetli ve özelleştirilebilir bir monitoring çözümü oluşturmaktı.

## Proje Görseli

![Web Monitor Dashboard](images/image1.png)

---

## Hangi problemi çözer?

- Dağınık servislerin merkezi izlenmesi
- Kesinti anlarının otomatik tespiti ve kaydı
- Sadece "up/down" değil, gecikme bazlı kalite takibi
- CI ve operasyon akışlarında SLO odaklı kontrol
- Küçük ekipler için self-hosted ve düşük maliyetli monitor altyapısı

## Hedef Kitle

- Bireysel geliştiriciler
- KOBİ teknik ekipleri
- DevOps / SRE mühendisleri
- Kurum içi NOC ve sistem yönetimi ekipleri

---

## Teknoloji Yığını

### Backend / Core
- Python 3.10+
- asyncio + aiohttp (asenkron check motoru)
- FastAPI + Uvicorn (dashboard API)

### Data / Storage
- SQLite (WAL modu)
- aiosqlite

### Frontend
- HTML + CSS + Vanilla JavaScript (statik dashboard)

### DevOps / Operasyon
- Docker + Docker Compose
- Nginx reverse proxy (metrics/health proxy ve auth)
- GitHub Actions (CI)
- Ruff + Pytest + Compile check + Gitleaks

---

## Mimari Özet

1. Hedef listesi (`targets.yaml` veya `links.txt`) yüklenir.
2. Monitor worker asenkron dalgalar halinde HTTP kontrolü yapar.
3. Sonuçlar SQLite veritabanına yazılır.
4. Incident ve durum bilgileri API ve CLI tarafında kullanılır.
5. Dashboard API'den veri çekerek son durumu gösterir.
6. Prometheus `/metrics` endpoint'i metrikleri dış sistemlere açar.

Kısa akış:

`Targets -> Async Runner -> SQLite -> API/CLI/Metrics -> Dashboard`

---

## Özellikler

- Asenkron monitor loop (yüksek hedef sayısında stabil çalışma)
- Retry + jitter + timeout guardrail'leri
- AIMD backpressure ile adaptif concurrency
- Incident raporlama (down/resolved)
- SLO raporu (`--slo-report`)
- Config doğrulama (`--validate-config`)
- Profil bazlı hedef dosyası desteği
- Slack / SMTP / Webhook / PagerDuty notifier desteği
- Dockerized çalıştırma ve CI pipeline

---

## Hemen Başla

Detaylı kurulum için `KURULUM.md` dosyasına bak.

Opsiyonel olarak `.env.example` dosyasını kopyalayıp kendi ortamına göre doldurabilirsin:

```bash
cp .env.example .env
```

En hızlı local demo:

```bash
cd /home/arda/software/WEB-MONITOR
python -m venv .venv
source .venv/bin/activate
pip install -r watchdog/requirements.txt

export WATCHDOG_TARGETS_FILE=watchdog/links.txt
export WATCHDOG_DB_PATH=watchdog.db

python watchdog/main.py --monitor
```

Ayrıca dashboard API:

```bash
cd /home/arda/software/WEB-MONITOR/watchdog
source /home/arda/software/WEB-MONITOR/.venv/bin/activate
uvicorn src.api.app:app --host 0.0.0.0 --port 8001
```

Tarayıcı:

`http://localhost:8001`

---

## `links.txt` ile kullanma

Bu projede plain text URL listesi doğrudan desteklenir.

Örnek:

```text
https://example.com
https://www.turkiye.gov.tr
https://www.google.com
```

Çalıştırma:

```bash
export WATCHDOG_TARGETS_FILE=watchdog/links.txt
python watchdog/main.py --monitor
```

İstersen `links.txt` dosyasını YAML hedef formatına çevirmek için:

```bash
python watchdog/scripts/links_to_targets.py \
  --links-file watchdog/links.txt \
  --output-file watchdog/config/targets_links.yaml
```

---

## Docker ile Çalıştırma

```bash
cd /home/arda/software/WEB-MONITOR
docker compose up -d --build
docker compose ps
```

Servisler:
- `watchdog-monitor`
- `watchdog-metrics`
- `watchdog-nginx`

Kontrol:

```bash
curl -s http://localhost:8080/health
```

Kapatma:

```bash
docker compose down
```

---

## CI (GitHub Actions)

`.github/workflows/ci.yml` içinde iki job vardır:

1. `secrets`: gitleaks ile secret scan
2. `test`: Python matrix üzerinde lint, format-check, test, compile check

Çalışan adımlar:
- `ruff check .`
- `ruff format --check .`
- `pytest watchdog`
- `python -m compileall watchdog/src`

---

## Güvenlik Notları

- `.env` ve `.env.*` dosyaları git'e dahil edilmez.
- SMTP, Slack vb. bilgiler environment değişkeni olarak verilir.
- Varsayılan SSRF korumaları aktiftir (private IP engeli).
- Metrics endpoint'ini production ortamında auth/network policy ile koru.
- Detaylı teknik notlar: `watchdog/docs/OPERASYON_VE_MIMARI_NOTLARI.md`

---

## Proje Yapısı

```text
WEB-MONITOR/
├─ watchdog/
│  ├─ main.py
│  ├─ links.txt
│  ├─ config/
│  ├─ src/
│  │  ├─ api/
│  │  ├─ core/
│  │  ├─ infrastructure/
│  │  ├─ models/
│  │  └─ services/
│  └─ tests/
├─ docker-compose.yml
├─ KURULUM.md
├─ README.md
└─ images/
```

---

## Geliştirici

**Arda Karadağ**

T.C. İÇİŞLERİ BAKANLIĞI NÜFUS VE VATANDAŞLIK İŞLERİ GENEL MÜDÜRLÜĞÜ (BVYS-YAZILIM GELİŞTİRME) BÜNYESİNDE STAJ ÇALIŞMASINDA GELİŞTİRİLMİŞTİR.
