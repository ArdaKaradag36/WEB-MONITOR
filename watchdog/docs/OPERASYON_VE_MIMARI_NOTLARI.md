# WatchDog — Operasyon ve Mimari Referansı

Bu belge, WatchDog'un teknik mimarisini, operasyonel kısıtlamalarını ve üretim
ortamına özgü yapılandırma ilkelerini kapsar. README'yi kısa tutmak amacıyla
ayrı bir referans belgesi olarak düzenlenmiştir. Sistem davranışını inceleyen
teknik ekiplere ve platforma entegrasyon yapacak mühendislere yöneliktir.

---

## Çekirdek Mimari

Monitor motoru Python'un `asyncio` ve `aiohttp` kütüphaneleri üzerine
inşa edilmiştir. Her izleme dalgası, hedefleri eş zamanlı olarak kontrol
eden ve sonuçları tek bir işlem bloğunda SQLite'a yazan bir görev kümesi
çalıştırır.

```
Targets YAML / TXT
      │
      ▼
 monitor_targets()          ← asyncio + aiohttp
      │
      ├─ SSRF Guard          ← DNS çözümleme + IP filtresi
      ├─ TLS Expiry Check    ← HTTPS hedeflerde opsiyonel
      ├─ HTTP Request        ← retry + jitter + timeout cap
      │
      ▼
  SQLite (WAL)              ← tek yazıcı, çoklu okuyucu
      │
      ├─ FastAPI /api/*      ← dashboard ve programatik erişim
      ├─ aiohttp /metrics    ← Prometheus formatı
      └─ CLI / TUI           ← rapor, incident, SLO
```

**Önemli kısıtlama:** SQLite mimarisi tek bir monitor işlemi için
tasarlanmıştır. Aynı veritabanı dosyasına birden fazla monitor süreci
eş zamanlı yazı yaparsa WAL kilitleri devreye girer ve veri tutarsızlığı
riski doğar. Yatay ölçekleme gereksiniminde her dağıtım kendi veritabanı
dosyasını yönetmelidir.

---

## Konfigürasyon Katmanı

Tüm çalışma zamanı ayarları `WATCHDOG_*` ortam değişkenlerinden okunur.
`.env` dosyası desteklenmekle birlikte üretim ortamlarında ortam değişkenleri
doğrudan container/servis yapılandırmasına enjekte edilmelidir.

**Profil Mekanizması:** `WATCHDOG_PROFILE` değişkeni tanımlandığında sistem
`config/targets_{PROFILE}.yaml` dosyasını varsayılan hedef listesi olarak
kullanır. `WATCHDOG_TARGETS_FILE` değişkeni açıkça tanımlanmışsa profile
göre otomatik seçim devre dışı kalır.

**Zaman Kısıtı:** `WATCHDOG_REQUEST_TIMEOUT_SECONDS` değeri her zaman
`WATCHDOG_POLL_INTERVAL_SECONDS` değerinden küçük olmalıdır. Bu kural
başlatma sırasında `AppSettings._validate_time_relationships` doğrulayıcısı
tarafından zorunlu kılınır; aksi hâlde sistem `ValidationError` fırlatır.

---

## Güvenlik Kontrolleri

### SSRF Koruması

Her HTTP isteğinden önce `_is_safe_url()` fonksiyonu hedef URL'yi aşağıdaki
açılardan doğrular:

- Yalnızca `http` ve `https` şemalarına izin verilir.
- SSH (22), Telnet (23), SMTP (25), POP3 (110), IMAP (143) portları
  reddedilir.
- Hedef hostname DNS üzerinden çözümlenir; çözümlenen IP'nin loopback,
  link-local veya özel (RFC 1918) bir adres olup olmadığı kontrol edilir.
- `WATCHDOG_ALLOW_PRIVATE_IPS=true` yalnızca güvenli iç ağ ortamlarında
  açılmalıdır. İnternet'e açık dağıtımlarda bu ayar asla etkinleştirilmemeli.

### Gövde Boyutu Sınırı

Yanıt gövdesi en fazla 50 KB okunur (`MAX_BODY_BYTES`). Bu sınır, büyük
yanıtların bellek tüketmesini engeller ve potansiyel zip-bomb saldırılarına
karşı bir önlem katmanı oluşturur.

### TLS Sertifika Kontrolü

Hedef bazında `tls_days_before_expiry_warning` alanı tanımlandığında sistem,
sertifikanın sona erme süresini kontrol eder ve eşiğin altına düştüğünde
hedefi `DOWN` olarak işaretler. Bu kontrol arka plan iş parçacığında
çalışır; ana asyncio döngüsünü bloke etmez.

### Gizli Bilgi Yönetimi

Kimlik bilgileri (SMTP şifresi, Slack webhook URL'si vb.) yalnızca ortam
değişkenleri aracılığıyla sağlanmalıdır. Bu bilgilerin YAML hedef
dosyalarına veya herhangi bir versiyon kontrol sistemine yazılması
kesinlikle yasaktır.

---

## Backpressure ve Adaptif Concurrency

Monitor döngüsü AIMD (Additive Increase / Multiplicative Decrease)
algoritmasıyla eş zamanlılık sınırını dinamik olarak ayarlar:

| Koşul | Eylem |
|-------|-------|
| Timeout oranı ≥ %30 veya 5xx oranı ≥ %50 veya dalga süresi > %80 poll interval | Concurrency × 0.7 |
| Timeout yok ve dalga süresi < %50 poll interval | Concurrency + 1 |
| Diğer | Değişiklik yok |

Bu davranış `_adjust_concurrency()` saf fonksiyonu içinde yalıtılmıştır;
yan etkisizdir ve birim testlerle doğrulanabilir.

---

## Circuit Breaker / Global Uyarı Baskılama

Bir dalga sonucunda hedeflerin %80'inden fazlası `DOWN` olarak raporlandığında
sistem global uyarı baskılamayı etkinleştirir. Bu mekanizma, kısa süreli ağ
kesintilerinde uyarı fırtınasını önler. Başarısızlık oranı %50'nin altına
indiğinde baskılama otomatik olarak devre dışı bırakılır.

Eşik değerleri `monitor.py` içindeki `HIGH_FAILURE_THRESHOLD` ve
`RECOVERY_THRESHOLD` sabitleriyle yapılandırılır. Bu değerleri değiştirmeden
önce `tests/test_backpressure_and_resilience.py` test dosyasını çalıştırın.

---

## Bakım Penceresi Entegrasyonu

`WATCHDOG_MAINTENANCE_WINDOWS_FILE` ile bir YAML dosyası tanımlandığında,
eşleşen URL'ler için aktif bakım penceresi süresince uyarı iletilmez. Kontrol
sonuçları veritabanına yazılmaya devam eder; yalnızca notifier katmanı atlanır.
Bu sayede bakım süreleri uptime istatistiklerini etkilemez.

---

## Veri Saklama (Retention)

`WATCHDOG_RETENTION_DAYS` (varsayılan: 7) ile belirlenen süreden eski kontrol
kayıtları her izleme dalgasının sonunda otomatik olarak temizlenir. Uzun vadeli
eğilim analizi için harici bir veri aktarım mekanizması (`--export-csv`) veya
Prometheus metrik depolaması tercih edilmelidir.

---

## Docker Dağıtım Rehberi

- `watchdog.db` dosyası kalıcı bir volume'e bağlanmalıdır; aksi hâlde
  container yeniden başlatıldığında tüm geçmiş veri kaybolur.
- `WATCHDOG_TARGETS_FILE` değişkeni container içindeki gerçek dosya yolunu
  göstermelidir.
- `/metrics` endpoint'i yalnızca güvenilir ağ segmentlerinden veya kimlik
  doğrulama katmanı (Nginx Basic Auth) arkasından erişilebilir olmalıdır.
- Üretimde Docker secret veya vault entegrasyonu üzerinden kimlik bilgilerini
  yönetmek, plain-text `.env` kullanımına göre tercih edilmelidir.

---

---

# WatchDog — Operations and Architecture Reference

*English translation follows the Turkish section above.*

This document covers WatchDog's technical architecture, operational
constraints, and production-specific configuration principles. It is
maintained as a separate reference to keep the main README concise.
Intended for engineering teams integrating the platform or operating it
in production environments.

---

## Core Architecture

The monitor engine is built on Python's `asyncio` and `aiohttp`. Each
monitoring wave runs a set of tasks that check targets concurrently and
persist results to SQLite within a single transaction block.

```
Targets YAML / TXT
      │
      ▼
 monitor_targets()          ← asyncio + aiohttp
      │
      ├─ SSRF Guard          ← DNS resolution + IP filter
      ├─ TLS Expiry Check    ← optional, HTTPS targets only
      ├─ HTTP Request        ← retry + jitter + timeout cap
      │
      ▼
  SQLite (WAL)              ← single writer, multiple readers
      │
      ├─ FastAPI /api/*      ← dashboard and programmatic access
      ├─ aiohttp /metrics    ← Prometheus format
      └─ CLI / TUI           ← report, incident, SLO
```

**Key constraint:** The SQLite architecture is designed for a single
monitor process. Concurrent writers on the same database file trigger WAL
locks and risk data inconsistency. For horizontal scaling, each deployment
must manage its own database file.

---

## Configuration Layer

All runtime settings are read from `WATCHDOG_*` environment variables.
`.env` files are supported but in production environments credentials should
be injected directly into container/service configuration rather than
checked-in files.

**Profile mechanism:** When `WATCHDOG_PROFILE` is set, the system
automatically selects `config/targets_{PROFILE}.yaml` as the target list.
If `WATCHDOG_TARGETS_FILE` is explicitly set, profile-based auto-selection
is disabled.

**Time constraint:** `WATCHDOG_REQUEST_TIMEOUT_SECONDS` must always be
strictly less than `WATCHDOG_POLL_INTERVAL_SECONDS`. This invariant is
enforced at startup by `AppSettings._validate_time_relationships`; the
system raises `ValidationError` if violated.

---

## Security Controls

### SSRF Protection

Before each HTTP request, `_is_safe_url()` validates the target URL on the
following dimensions:

- Only `http` and `https` schemes are permitted.
- SSH (22), Telnet (23), SMTP (25), POP3 (110), IMAP (143) ports are denied.
- The target hostname is resolved via DNS; the resolved IP is checked for
  loopback, link-local, or private (RFC 1918) addresses.
- `WATCHDOG_ALLOW_PRIVATE_IPS=true` must only be set in trusted internal
  network environments. Never enable this in internet-facing deployments.

### Response Body Size Limit

Response bodies are read up to a maximum of 50 KB (`MAX_BODY_BYTES`). This
prevents large responses from consuming excessive memory and provides a
mitigation layer against zip-bomb style attacks.

### TLS Certificate Check

When a target defines `tls_days_before_expiry_warning`, the system checks
the certificate's expiry and marks the target `DOWN` when the threshold is
crossed. This check runs in a background thread and does not block the main
asyncio event loop.

### Credential Management

Credentials (SMTP password, Slack webhook URL, etc.) must be provided only
via environment variables. Writing these values into YAML target files or
any version control system is strictly prohibited.

---

## Backpressure and Adaptive Concurrency

The monitor loop dynamically adjusts its concurrency limit using an AIMD
(Additive Increase / Multiplicative Decrease) algorithm:

| Condition | Action |
|-----------|--------|
| Timeout ratio ≥ 30% or 5xx ratio ≥ 50% or wave duration > 80% of poll interval | Concurrency × 0.7 |
| No timeouts and wave duration < 50% of poll interval | Concurrency + 1 |
| Otherwise | No change |

This behaviour is isolated in the pure function `_adjust_concurrency()`,
which is side-effect free and verifiable through unit tests.

---

## Circuit Breaker / Global Alert Suppression

When more than 80% of targets report `DOWN` in a single wave, the system
enables global alert suppression. This mechanism prevents alert storms
during brief network outages. Suppression is automatically lifted when the
failure rate drops below 50%.

Threshold values are configured via `HIGH_FAILURE_THRESHOLD` and
`RECOVERY_THRESHOLD` constants in `monitor.py`. Run
`tests/test_backpressure_and_resilience.py` before modifying these values.

---

## Maintenance Window Integration

When `WATCHDOG_MAINTENANCE_WINDOWS_FILE` points to a valid YAML file,
alerts are suppressed for matching URLs during active maintenance windows.
Check results continue to be written to the database; only the notifier
layer is bypassed. This ensures maintenance periods do not distort uptime
statistics.

---

## Data Retention

Records older than `WATCHDOG_RETENTION_DAYS` (default: 7) are automatically
purged at the end of each monitoring wave. For long-term trend analysis, use
the external export mechanism (`--export-csv`) or Prometheus metric storage.

---

## Docker Deployment Guide

- `watchdog.db` must be mounted on a persistent volume; otherwise all
  historical data is lost on container restart.
- `WATCHDOG_TARGETS_FILE` must point to the correct file path inside the
  container.
- The `/metrics` endpoint should only be accessible from trusted network
  segments or behind an authentication layer (e.g., Nginx Basic Auth).
- In production, prefer Docker secrets or a vault integration over
  plain-text `.env` files for credential management.
