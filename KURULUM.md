## WatchDog – Hızlı Kurulum ve İlk Çalıştırma

Bu dosya, projeyi **en basit şekilde ayağa kaldırmak** için kısa bir rehberdir.
Detaylı tüm dokümantasyon için `README.md` dosyasına bakabilirsin.

---

## 1. Gereksinimler

- Python **3.10+**
- Git
- (İsteğe bağlı) Docker ve Docker Compose

---

## 2. Kaynağı indir

```bash
git clone <repo-url> WEB-MONITOR
cd WEB-MONITOR
```

`<repo-url>` yerine kendi Git deposunun HTTPS/SSH adresini yaz.

---

## 3. Python ile hızlı kurulum

### 3.1 Sanal ortam oluştur ve bağımlılıkları yükle

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate

pip install -r watchdog/requirements.txt
```

### 3.2 Basit hedef dosyasını kullanarak monitor’u başlat

Varsayılan, birkaç örnek hedef içeren konfig ile:

```bash
export WATCHDOG_TARGETS_FILE=watchdog/config/targets.yaml
export WATCHDOG_DB_PATH=watchdog.db

python watchdog/main.py --monitor
```

Terminalde periyodik health check loglarını görmelisin.

### 3.3 İlk raporu almak

Bir süre çalıştıktan sonra (örneğin birkaç dakika), yeni bir terminal aç:

```bash
cd WEB-MONITOR
source .venv/bin/activate           # Windows: .venv\Scripts\activate

python watchdog/main.py --report --last-hours 1
```

Son 1 saatin uptime/latency özet tablosu yazdırılır.

---

## 4. Docker ile çalıştırma (tek komut)

Docker ve Docker Compose yüklüyse:

```bash
cd WEB-MONITOR
docker compose up -d --build
```

Beklenen servisler:

- `watchdog-monitor`
- `watchdog-metrics`
- `watchdog-nginx`

Durumu kontrol etmek için:

```bash
docker compose ps
```

Health ve metrics endpoint’leri:

```bash
curl -s http://localhost:8080/health
curl -s http://localhost:8080/metrics | head -40
```

Stack’i durdurmak için:

```bash
docker compose down
```

---

## 5. En basit hedef dosyasıyla denemek (opsiyonel)

Tek bir endpoint’i izlemek için minimal konfig:

```bash
export WATCHDOG_TARGETS_FILE=watchdog/config/targets_minimal.yaml
python watchdog/main.py --monitor
```

Bu dosya, `https://example.com/health` için basit bir health check içerir.

