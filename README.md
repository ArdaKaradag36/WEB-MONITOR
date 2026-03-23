# WEB-MONITOR (WatchDog)

NVI bunyesinde staj surecimde gelistirdigim bu proje, kamu ve ozel web servislerini merkezi olarak izlemek icin tasarlanmis self-hosted bir web monitor uygulamasidir. Sistem; hedef URL'leri periyodik olarak kontrol eder, uptime/latency verilerini kaydeder, kesinti anlarini incident olarak raporlar ve hem API hem dashboard hem de Prometheus metrikleri uzerinden operasyon ekiplerine gorunurluk saglar.

## Portfoy Ozeti

Bu projeyi tek basima, uretim mantigina yakin bir yaklasimla gelistirdim: asenkron izleme motoru, SQLite tabanli veri katmani, FastAPI ile dashboard API'si, Docker tabanli calistirma ve GitHub Actions ile kalite kontrol adimlarini tek bir sistemde topladim. Amacim, kurum ici veya internet uzeri kritik servislerin kesinti ve performans problemlerini erken tespit edebilen, dusuk maliyetli ve ozellestirilebilir bir monitoring cozumu olusturmakti.

## Proje Gorseli

![Web Monitor Dashboard](images/image1.png)

---

## Hangi problemi cozer?

- Daginik servislerin merkezi izlenmesi
- Kesinti anlarinin otomatik tespiti ve kaydi
- Sadece "up/down" degil, gecikme bazli kalite takibi
- CI ve operasyon akislarinda SLO odakli kontrol
- Kucuk ekipler icin self-hosted ve dusuk maliyetli monitor altyapisi

## Hedef Kitle

- Bireysel gelistiriciler
- KOBI teknik ekipleri
- DevOps / SRE muhendisleri
- Kurum ici NOC ve sistem yonetimi ekipleri

---

## Teknoloji Yigini

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

## Mimari Ozet

1. Hedef listesi (`targets.yaml` veya `links.txt`) yuklenir.
2. Monitor worker asenkron dalgalar halinde HTTP kontrolu yapar.
3. Sonuclar SQLite veritabanina yazilir.
4. Incident ve durum bilgileri API ve CLI tarafinda kullanilir.
5. Dashboard API'den veri cekerek son durumu gosterir.
6. Prometheus `/metrics` endpoint'i metrikleri dis sistemlere acar.

Kisa akıs:

`Targets -> Async Runner -> SQLite -> API/CLI/Metrics -> Dashboard`

---

## Ozellikler

- Asenkron monitor loop (yuksek hedef sayisinda stabil calisma)
- Retry + jitter + timeout guardrail'leri
- AIMD backpressure ile adaptif concurrency
- Incident raporlama (down/resolved)
- SLO raporu (`--slo-report`)
- Config dogrulama (`--validate-config`)
- Profil bazli hedef dosyasi destegi
- Slack / SMTP / Webhook / PagerDuty notifier destegi
- Dockerized calistirma ve CI pipeline

---

## Hemen Basla

Detayli kurulum icin `KURULUM.md` dosyasina bak.

Opsiyonel olarak `.env.example` dosyasini kopyalayip kendi ortamina gore doldurabilirsin:

```bash
cp .env.example .env
```

En hizli local demo:

```bash
cd /home/arda/software/WEB-MONITOR
python -m venv .venv
source .venv/bin/activate
pip install -r watchdog/requirements.txt

export WATCHDOG_TARGETS_FILE=watchdog/links.txt
export WATCHDOG_DB_PATH=watchdog.db

python watchdog/main.py --monitor
```

Ayrica dashboard API:

```bash
cd /home/arda/software/WEB-MONITOR/watchdog
source /home/arda/software/WEB-MONITOR/.venv/bin/activate
uvicorn src.api.app:app --host 0.0.0.0 --port 8001
```

Tarayici:

`http://localhost:8001`

---

## `links.txt` ile kullanma

Bu projede plain text URL listesi dogrudan desteklenir.

Ornek:

```text
https://example.com
https://www.turkiye.gov.tr
https://www.google.com
```

Calistirma:

```bash
export WATCHDOG_TARGETS_FILE=watchdog/links.txt
python watchdog/main.py --monitor
```

Istersen `links.txt` dosyasini YAML hedef formatina cevirmek icin:

```bash
python watchdog/scripts/links_to_targets.py \
  --links-file watchdog/links.txt \
  --output-file watchdog/config/targets_links.yaml
```

---

## Docker ile Calistirma

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

`.github/workflows/ci.yml` icinde iki job vardir:

1. `secrets`: gitleaks ile secret scan
2. `test`: Python matrix uzerinde lint, format-check, test, compile check

Calisan adimlar:
- `ruff check .`
- `ruff format --check .`
- `pytest watchdog`
- `python -m compileall watchdog/src`

---

## Guvenlik Notlari

- `.env` ve `.env.*` dosyalari git'e dahil edilmez.
- SMTP, Slack vb. bilgiler environment degiskeni olarak verilir.
- Varsayilan SSRF korumalari aktiftir (private IP engeli).
- Metrics endpoint'ini production ortaminda auth/network policy ile koru.
- Detayli teknik notlar: `watchdog/docs/OPERASYON_VE_MIMARI_NOTLARI.md`

---

## Proje Yapisi

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

## Gelistirici

**Arda Karadag**

T.C. İÇİŞLERİ BAKANLIĞI NÜFUS VE VATANDAŞLIK İŞLERİ GENEL MÜDÜRLÜĞÜ (BVYS-YAZILIM GELİŞTİRME) BÜNYESİNDE STAJ ÇALIŞMASINDA GELİŞTİRİLMİŞTİR.
