## WatchDog Operasyon ve Mimari Notlari

Bu dosya, README'yi sade tutup kritik teknik ayrintilari kaybetmemek icin hazirlandi.

---

## Cekirdek Mimari

- Monitor motoru `asyncio` + `aiohttp` ile asenkron check dalgalari calistirir.
- Sonuclar SQLite'a yazilir (tek writer, coklu reader modeli).
- API ve dashboard veriyi ayni veritabanindan okur.
- Metrics endpoint'i Prometheus formatinda sunulur.

---

## Konfigurasyon Mantigi

- Ayarlar `WATCHDOG_*` environment degiskenlerinden okunur.
- Profil kullanimi (`WATCHDOG_PROFILE`) ile farkli hedef setleri secilebilir.
- Hedef kaynagi hem YAML hem `links.txt` (satir bazli URL) olabilir.

---

## Operasyonel Guardrail'ler

- `WATCHDOG_REQUEST_TIMEOUT_SECONDS < WATCHDOG_POLL_INTERVAL_SECONDS` olmalidir.
- Retry sayisi yuksek tutuldugunda dalga suresi uzar; prod'da kontrollu kullanilmalidir.
- Varsayilan SSRF korumalari private/loopback hedefleri engeller.
- Gerekirse sadece kurum ici aglar icin `WATCHDOG_ALLOW_PRIVATE_IPS=true` acilabilir.

---

## Incident ve Bildirim Akisi

- Check sonucu state degistirdiginde incident kaydi olusur.
- Bildirim katmani Slack/SMTP/Webhook/PagerDuty hedeflerine fan-out yapabilir.
- Bakim penceresi tanimlari ile alarm gurultusu azaltilabilir.

---

## Veri ve Performans Notlari

- SQLite WAL modu ile monitor yazma + API okuma senaryosunda dengeli calisir.
- Cok yuksek sorgu trafiginde raporlama isleri ayrik bir sisteme aktarilabilir.
- Concurrency davranisi backpressure ile adaptif hale getirilir.

---

## CI ve Kalite

GitHub Actions adimlari:

- Secret scan (`gitleaks`)
- Lint (`ruff check`)
- Format check (`ruff format --check`)
- Test (`pytest watchdog`)
- Compile check (`python -m compileall watchdog/src`)

---

## Docker Operasyon Onerileri

- `watchdog.db` kalici volume'de tutulmalidir.
- `WATCHDOG_TARGETS_FILE` container icinde dogru path'e map edilmelidir.
- Metrics endpoint'i network policy veya auth ile korunmalidir.
