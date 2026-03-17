# WatchDog — Terminal Analizi, Rapor ve Rakip Karşılaştırması

**Tarih:** 11 Mart 2025  
**Kapsam:** Terminaller, mevcut durum, eksiklik listesi, rakip firmalara göre analiz.

---

## 1. Terminal Özeti

| Terminal | Konum | Durum | Not |
|----------|--------|--------|-----|
| **2** | `WEB-MONITOR` | Boşta | Sadece `.venv` aktif. |
| **4** | `watchdog/` | **Aktif** | `python main.py --monitor` çalışıyor; 40 hedef (chaos). |
| **5** | `watchdog/` | Kapalı (exit 0) | `--monitor-dashboard` çalıştırıldı; tablo sonunda dolu göründü. |

### 1.1 Terminal 4 (Monitor) — Gözlemler

- **Build:** `docker compose build` başarılı. Uyarı: `version` artık kullanılmıyor (docker-compose.yml’den kaldırılabilir).
- **Çalışma yolu:** Önce `python main.py --monitor` proje kökünden denendi → `main.py` bulunamadı. Doğru kullanım: `cd watchdog/` sonra `python main.py --monitor`.
- **Hedef dosyası:** `.env` → `WATCHDOG_TARGETS_FILE=config/targets_chaos.yaml` (40 hedef). Normal 10 hedefli set için `config/targets.yaml` kullanılmalı.
- **Davranış (beklenen):**
  - SSRF: `10.255.255.x` adresleri engellendi (Blocked potential SSRF target).
  - DNS: `nonexistent.blackhole.watchdog.test` çözülemedi.
  - Retry: 5xx/503 için jitter ile yeniden deneme yapılıyor.
  - Backpressure: Concurrency 15 → 10 → 7 → 4 → 2 düşürüldü (wave süresi ve timeout oranına göre).
  - CRITICAL/RESOLVED: Ardışık 3 başarısızlıkta CRITICAL, toparlanmada RESOLVED tetikleniyor.
- **Slack:** Webhook 404 dönüyor (dummy URL). Her alert’te Slack’e istek atılıp uyarı loglanıyor; webhook yoksa/geçersizse sessizce atlanması veya tek seferlik uyarı daha temiz olur.

### 1.2 Terminal 5 (Dashboard) — Gözlemler

- Dashboard başladı, “last 1h” penceresinde bir süre tablo **satırları boş** (sadece başlık tekrarları), sonra **tek seferde 40 URL’li dolu tablo** göründü.
- Olası nedenler: İlk dakikalarda veri yoktu (monitor henüz yazmamıştı) veya farklı DB dosyası (örn. farklı cwd’de `watchdog.db`). Aynı `WATCHDOG_DB_PATH` ve aynı çalışma dizini kullanıldığından emin olmak iyi olur.
- Çıkış exit code 0; kullanıcı Ctrl+C ile kapattı.

---

## 2. Mevcut Durum Özeti

| Alan | Durum | Açıklama |
|------|--------|----------|
| Monitor döngüsü | ✅ | Async, 40 hedefli chaos setinde kararlı çalışıyor. |
| SSRF koruması | ✅ | Özel IP’ler engelleniyor. |
| Backpressure (AIMD) | ✅ | Yük altında concurrency düşüyor. |
| Retry + jitter | ✅ | Geçici 5xx/timeout’larda devreye giriyor. |
| Circuit breaker / alert baskılama | ✅ | Toplu arızalarda bildirim fırtınası azaltılıyor. |
| CRITICAL/RESOLVED (Console) | ✅ | Rich ile kutu içi uyarılar. |
| Slack webhook | ⚠️ | 404 (sahte URL); hata yönetimi iyileştirilebilir. |
| Dashboard (TUI) | ✅ | Çalışıyor; ilk refresh’lerde boş tablo olabiliyor. |
| Prometheus /metrics | ✅ | P50/P95/P99, uptime, telemetry. |
| Docker + Nginx | ✅ | Build alıyor; Basic Auth ile /metrics. |
| Veri seti | ⚠️ | Varsayılan .env hâlâ chaos (40). Normal set 10 hedef (targets.yaml). |

---

## 3. Eksiklik ve İyileştirme Listesi

### 3.1 Yüksek Öncelik

1. **Slack webhook yoksa/geçersizse davranış**
   - Webhook 404/5xx’te her seferinde WARNING yerine: ilk hatada bir kez uyarı, sonra sessizce atla veya “Slack disabled” modu.
   - Böylece log gürültüsü azalır.

2. **Dashboard “boş tablo” deneyimi**
   - Veri yokken “Son 1 saatte veri yok” veya “Monitor’ü başlatın / bekleyin” gibi tek satırlık bilgi gösterilebilir.
   - Aynı DB yolunun kullanıldığı (monitor ile dashboard) dokümante edilsin veya tek bir `WATCHDOG_DB_PATH` default’u net olsun.

3. **Hedef dosyası netliği**
   - `.env` örnekte varsayılan `config/targets.yaml` olsun; chaos için ayrı bir profil (ör. `WATCHDOG_TARGETS_FILE=config/targets_chaos.yaml`) dokümante edilsin.
   - README’de “Normal çalışma: targets.yaml, stres testi: targets_chaos.yaml” açık yazılsın.

### 3.2 Orta Öncelik

4. **docker-compose uyarısı**
   - `version: "3.9"` kaldırılarak “attribute version is obsolete” uyarısı giderilebilir.

5. **main.py konumu**
   - Proje kökünde `python main.py` denendiğinde hata alınıyor. README/Quickstart’ta “Tüm komutlar `watchdog/` içinden” veya “Proje kökünden: `python watchdog/main.py` (PYTHONPATH ile)” net yazılsın.

6. **E-posta (SMTP) testi**
   - SMTP yapılandırıldığında gerçek teslimat ve “test e-postası” akışı dokümante veya basit bir `--test-notifiers` ile test edilebilir.

### 3.3 Düşük Öncelik

7. **TLS sertifika süresi**
   - Hedef URL’in SSL sertifikasının süresi kontrol edilmiyor; rakiplerde var (TLS expiry check).

8. **Çok bölgeli (multi-location) kontrol**
   - Tek sunucudan probe; rakipler coğrafi dağılımlı noktalardan kontrol eder.

9. **Bakım penceresi (maintenance window)**
   - Belirli saatlerde alert’leri susturma; rakiplerde sık görülür.

---

## 4. Rakip Firmalara Göre Karşılaştırma

Aşağıdaki tablo, aynı tür yazılımlar (uptime / synthetic monitoring) yapan ürünlerle WatchDog’u özellik bazında karşılaştırır.

| Özellik | WatchDog | Prometheus Blackbox Exporter | Uptime Kuma | UptimeRobot / Pingdom (SaaS) |
|--------|----------|------------------------------|-------------|-------------------------------|
| **HTTP(s) uptime** | ✅ | ✅ | ✅ | ✅ |
| **Async / yüksek hedef sayısı** | ✅ (asyncio, semaphore) | ✅ (Prometheus scrape) | Orta | SaaS, sınır plana göre |
| **P50/P95/P99 latency** | ✅ | ✅ (histogram) | Sınırlı | ✅ (çoğu planda) |
| **Prometheus /metrics** | ✅ | ✅ (native) | Eklenti/export | Genelde API/entegrasyon |
| **Anti-SSRF / güvenlik** | ✅ (DNS+IP filtre) | Yapılandırmaya bağlı | Genelde yok | SaaS, onlar yönetir |
| **OOM koruması (body limit)** | ✅ (50KB) | Scrape limitleri var | Değişir | N/A |
| **Backpressure / adaptive concurrency** | ✅ (AIMD) | Scrape interval ile | Yok | N/A |
| **Circuit breaker / alert baskılama** | ✅ | Yok (alert rules ayrı) | Kısmen | Var |
| **Stateful alert (CRITICAL/RESOLVED)** | ✅ | Alertmanager ile | ✅ | ✅ |
| **Slack / e-posta** | ✅ | Alertmanager | ✅ (zengin) | ✅ |
| **Web arayüz (tarayıcı)** | ❌ | Grafana + Prometheus | ✅ (tam UI) | ✅ (ana ürün) |
| **TUI / terminal dashboard** | ✅ | ❌ | ❌ | ❌ |
| **Kendi sunucunda, sıfır SaaS** | ✅ | ✅ | ✅ (self-hosted) | ❌ |
| **TLS sertifika süresi** | ❌ | ✅ (module) | ✅ | ✅ |
| **TCP / ICMP / DNS probe** | ❌ (sadece HTTP) | ✅ (modüller) | ✅ | ✅ |
| **Çok bölge (multi-location)** | ❌ | Dağıtık Prometheus ile | Sınırlı | ✅ (SaaS) |
| **Bakım penceresi** | ❌ | Downtime/silence ile | Var | Var |
| **Kurulum / operasyon** | Docker, tek repo | Prometheus stack | Docker / manuel | Kayıt, kredi kartı |

---

## 5. WatchDog’un Güçlü Yönleri (Rakiplere Göre)

- **Hafif ve tek bileşen:** Tek repo, SQLite, ek servis (Prometheus/Alertmanager) zorunlu değil; CLI + TUI + metrics aynı kod tabanında.
- **SRE odaklı güvenlik:** Anti-SSRF, body limit, backpressure ve circuit breaker tek üründe; Blackbox Exporter’da bunlar ayrı konfigürasyon/alerting katmanında.
- **Terminal/NOC kullanımı:** `--monitor-dashboard` ve `--report` / `--incidents` ile sunucu üzerinde hızlı teşhis; rakiplerde çoğunlukla web UI veya Grafana gerekir.
- **CI entegrasyonu:** `--ci` ile SLA’ya göre exit code; pipeline’da kullanılabilir.
- **Şeffaflık:** Açık kaynak, tüm mantık kodda; SaaS’ta “kutu” yok.

---

## 6. Rakiplere Göre En Belirgin Eksikler

1. **Web UI yok:** Yönetim ve raporlama tamamen CLI/TUI; Uptime Kuma / Pingdom tarzı tarayıcı arayüzü yok.
2. **Sadece HTTP/HTTPS:** TCP ping, ICMP, DNS-only probe yok; Blackbox Exporter ve birçok SaaS’ta var.
3. **TLS sertifika süresi kontrolü yok:** Sertifika bitiş tarihi kontrolü eklenebilir.
4. **Tek lokasyon:** Çok bölgeli (multi-region) probe yok; coğrafi dağılım için birden fazla deployment gerekir.
5. **Bakım penceresi:** Planlı bakım saatlerinde alert susturma özelliği yok.

---

## 7. Kısa Aksiyon Özeti

- **Hemen:** Slack webhook 404/geçersiz durumunda log gürültüsünü azalt; dashboard’da “veri yok” mesajı ekle; `.env` varsayılanını `targets.yaml` yap ve chaos’u dokümante et.
- **Kısa vade:** docker-compose `version` uyarısını kaldır; README’de çalıştırma yolu (watchdog/ vs kök) netleştir.
- **Orta vade:** İsteğe bağlı TLS expiry check; bakım penceresi (opsiyonel).
- **Uzun vade:** Basit bir web UI veya TCP/DNS probe modülleri rakiplerle özellik eşlemesini güçlendirir.

Bu rapor, terminal çıktıları ve mevcut kod tabanına dayanarak hazırlanmıştır; rakip bilgileri genel piyasa bilgisi ile desteklenmiştir.
