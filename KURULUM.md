## WEB-MONITOR Kurulum Rehberi

Bu dokuman, projeyi sifirdan kurup calistirmak, sonra tekrar acmak ve Docker/CI akislarini anlamak icin hazirlandi.

---

## 1) Gereksinimler

- Python 3.10+
- Git
- (Opsiyonel) Docker + Docker Compose

Linux icin ekstra faydali:
- `xdg-open` (dashboard'i terminalden acmak icin)

---

## 2) Projeyi cekme

```bash
git clone <repo-url> WEB-MONITOR
cd WEB-MONITOR
```

---

## 3) Ilk local kurulum (Python)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r watchdog/requirements.txt
```

### 3.1 `links.txt` ile monitor baslatma

```bash
cd /home/arda/software/WEB-MONITOR
source .venv/bin/activate

export WATCHDOG_TARGETS_FILE=watchdog/links.txt
export WATCHDOG_DB_PATH=watchdog.db

python watchdog/main.py --monitor
```

> Bu terminal acik kalir; monitor burada calisir.

### 3.2 Dashboard API baslatma

`src` import yolu nedeniyle bu komut `watchdog/` klasoru icinden calismalidir:

```bash
cd /home/arda/software/WEB-MONITOR/watchdog
source /home/arda/software/WEB-MONITOR/.venv/bin/activate

export WATCHDOG_TARGETS_FILE=/home/arda/software/WEB-MONITOR/watchdog/links.txt
export WATCHDOG_DB_PATH=/home/arda/software/WEB-MONITOR/watchdog.db

uvicorn src.api.app:app --host 0.0.0.0 --port 8001
```

Tarayici:

```bash
xdg-open http://localhost:8001
```

---

## 4) Sonradan tekrar calistirma (guncel kullanim)

Projeyi daha once kurduysan:

### Terminal-1
```bash
cd /home/arda/software/WEB-MONITOR
source .venv/bin/activate
export WATCHDOG_TARGETS_FILE=watchdog/links.txt
export WATCHDOG_DB_PATH=watchdog.db
python watchdog/main.py --monitor
```

### Terminal-2
```bash
cd /home/arda/software/WEB-MONITOR/watchdog
source /home/arda/software/WEB-MONITOR/.venv/bin/activate
export WATCHDOG_TARGETS_FILE=/home/arda/software/WEB-MONITOR/watchdog/links.txt
export WATCHDOG_DB_PATH=/home/arda/software/WEB-MONITOR/watchdog.db
uvicorn src.api.app:app --host 0.0.0.0 --port 8001
```

Dashboard:
- `http://localhost:8001`

---

## 5) Temel komutlar

Repo root'tan:

```bash
python watchdog/main.py --validate-config
python watchdog/main.py --report --last-hours 1
python watchdog/main.py --status --last-minutes 5
python watchdog/main.py --incidents --last-hours 24
python watchdog/main.py --slo-report --last-hours 24
```

Metrics server (tek basina):

```bash
python watchdog/main.py --metrics-server --metrics-host 0.0.0.0 --metrics-port 9100
```

---

## 6) Docker ile calistirma

```bash
cd /home/arda/software/WEB-MONITOR
docker compose up -d --build
docker compose ps
```

Beklenen:
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

Log inceleme:

```bash
docker compose logs -f watchdog-monitor
docker compose logs -f watchdog-metrics
docker compose logs -f nginx
```

---

## 7) Environment degiskenleri

En cok kullanilanlar:

- `WATCHDOG_TARGETS_FILE`
- `WATCHDOG_DB_PATH`
- `WATCHDOG_POLL_INTERVAL_SECONDS`
- `WATCHDOG_REQUEST_TIMEOUT_SECONDS`
- `WATCHDOG_MAX_CONCURRENT_REQUESTS`
- `WATCHDOG_MAX_RETRIES`
- `WATCHDOG_ALLOW_PRIVATE_IPS`
- `WATCHDOG_SLACK_WEBHOOK_URL`
- `WATCHDOG_SMTP_*`
- `WATCHDOG_CI_CRITICAL_SERVICES_FILE`
- `WATCHDOG_MAINTENANCE_WINDOWS_FILE`

Ornek:

```bash
export WATCHDOG_TARGETS_FILE=watchdog/links.txt
export WATCHDOG_DB_PATH=watchdog.db
export WATCHDOG_POLL_INTERVAL_SECONDS=60
export WATCHDOG_REQUEST_TIMEOUT_SECONDS=5
```

---

## 8) SMTP / Slack notifier (opsiyonel)

SMTP ornegi:

```bash
export WATCHDOG_SMTP_HOST=smtp.gmail.com
export WATCHDOG_SMTP_PORT=587
export WATCHDOG_SMTP_USERNAME="<smtp-username>"
export WATCHDOG_SMTP_PASSWORD="<smtp-password-or-app-password>"
export WATCHDOG_SMTP_FROM="noreply@example.com"
export WATCHDOG_SMTP_TO="ops@example.com"
```

Slack:

```bash
export WATCHDOG_SLACK_WEBHOOK_URL="https://hooks.slack.com/services/XXXX/XXXX/XXXX"
```

Test mail:

```bash
python watchdog/main.py --send-test-email
```

---

## 9) CI / GitHub Actions

Pipeline dosyasi: `.github/workflows/ci.yml`

Calisan kontroller:
- gitleaks secret scan
- ruff lint
- ruff format check
- pytest
- compile check

Local'de CI benzeri calistirma:

```bash
source .venv/bin/activate
ruff check .
ruff format --check .
pytest watchdog
python -m compileall watchdog/src
```

---

## 10) `.gitignore` kontrolu

Repoda asagidaki kritik ignore kurallari zaten mevcut:

- `.venv/`, `venv/`, `env/`
- `.env`, `.env.*`
- `*.db`, `*.db-shm`, `*.db-wal`
- `*.log`
- `__pycache__/`, `.pytest_cache/`

Bu sayede local secret, DB ve log dosyalari commit'e girmez.

---

## 11) Sik karsilasilan hata ve cozum

### Hata: `ModuleNotFoundError: No module named 'src'`

Neden:
- API komutunu repo root'tan `uvicorn watchdog.src.api.app:app` ile calistirmak.

Cozum:
- `watchdog/` klasorune girip `uvicorn src.api.app:app` calistir.

### Hata: Dashboard aciliyor ama veri yok

Kontrol:
- `--monitor` ayri terminalde calisiyor mu?
- `WATCHDOG_DB_PATH` monitor ve API tarafinda ayni mi?
- `WATCHDOG_TARGETS_FILE` dogru dosyaya mi isaret ediyor?

---

## 12) Hedef dosya secenekleri

- `watchdog/links.txt` (satir basina URL)
- `watchdog/config/targets.yaml` (YAML)
- `watchdog/config/targets_public_institutions.yaml`
- `watchdog/config/targets_public_institutions_expanded.yaml`
- `watchdog/config/targets_chaos.yaml`

---

Bu dosya hizli uygulama odakli tutuldu. Mimari ve proje tanitimi icin `README.md` dosyasina gec.
