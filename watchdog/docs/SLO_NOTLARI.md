# WatchDog — SLO Yapılandırması ve Değerlendirme Referansı

Bu belge, WatchDog'un SLO (Service Level Objective) motorunun nasıl
çalıştığını, yapılandırma dosyasının nasıl oluşturulacağını ve
değerlendirme sonuçlarının nasıl yorumlanacağını açıklar.

---

## Genel Bakış

SLO motoru, `config/slo.yaml` içinde tanımlanan servis grupları için
belirli bir zaman penceresi boyunca **uptime** ve **p95 gecikme** hedeflerini
değerlendirir. Her servis, URL substring eşleştirmesiyle hedef listesindeki
ilgili endpoint'lere bağlanır.

Değerlendirme sonuçları üç durumdan birini üretir:

| Durum | Koşul |
|-------|-------|
| `PASS` | Hem uptime hem p95 gecikme hedefi tutturulmuş |
| `PARTIAL` | Hedeflerden yalnızca biri tutturulmuş |
| `FAIL` | Hiçbir hedef tutturulamamış |

Bu durum etiketleri dashboard (`/api/slo`), CLI (`--slo-report`) ve
Prometheus `/metrics` endpoint'i tarafından tutarlı biçimde kullanılır.

---

## Yapılandırma Dosyası Formatı

```yaml
# config/slo.yaml

services:
  - name: "e-Devlet Kapısı"
    url_contains: "turkiye.gov.tr"
    target_uptime_percent: 99.5
    target_p95_ms: 4000
    window_hours: 24

  - name: "Kurumsal API"
    url_contains: "api.example.com"
    target_uptime_percent: 99.9
    target_p95_ms: 500
    window_hours: 1
```

**Alan açıklamaları:**

| Alan | Zorunlu | Açıklama |
|------|---------|----------|
| `name` | Evet | Servisi temsil eden okunabilir etiket |
| `url_contains` | Evet | Hedef URL'lerde aranacak substring |
| `target_uptime_percent` | Evet | Hedef uptime yüzdesi (0 < değer ≤ 100) |
| `target_p95_ms` | Evet | Hedef p95 gecikme eşiği, milisaniye |
| `window_hours` | Hayır | Değerlendirme penceresi (varsayılan: 24 saat) |

---

## Çalıştırma

```bash
python watchdog/main.py --slo-report --last-hours 24
```

API üzerinden:

```
GET /api/slo
```

---

## Eşleştirme Mantığı

`url_contains` alanı, hedef listenizde kayıtlı URL'lere basit bir substring
eşleşmesiyle uygulanır. Bir URL birden fazla servis tanımıyla eşleşirse
her servisin kendi uptime/p95 ortalaması bağımsız olarak hesaplanır.

Belirli bir zaman penceresinde hiç eşleşen URL yoksa veya o pencerede
kontrol kaydı bulunmuyorsa, ilgili servis otomatik olarak `FAIL` durumuna
düşer.

---

## Üretim Ortamı İçin Notlar

- SLO hedeflerini gerçekçi tutun. Özellikle yüksek gecikme değişkenliğine
  sahip kamu hizmetleri için katı p95 eşikleri sürekli `PARTIAL` uyarısına
  yol açabilir.
- `window_hours` değerini izleme yoğunluğuna göre ayarlayın: 1 saatlik
  pencere en az birkaç on kontrol içermelidir; aksi hâlde istatistiksel
  güvenilirlik düşer.
- SLO değerlendirmesi yalnızca veritabanındaki mevcut kontrol kayıtlarına
  dayanır. Monitor işlemi çalışmıyorsa veya `WATCHDOG_DB_PATH` yanlış
  yapılandırılmışsa değerlendirme sıfır veri üzerinden çalışır.

---

---

# WatchDog — SLO Configuration and Evaluation Reference

*English translation follows the Turkish section above.*

This document explains how WatchDog's SLO (Service Level Objective) engine
works, how to build the configuration file, and how to interpret evaluation
results.

---

## Overview

The SLO engine evaluates **uptime** and **p95 latency** objectives for
service groups defined in `config/slo.yaml` over a configurable time window.
Each service is mapped to the relevant endpoints in the target list via
URL substring matching.

Evaluation produces one of three states:

| State | Condition |
|-------|-----------|
| `PASS` | Both uptime and p95 latency targets met |
| `PARTIAL` | Only one of the two targets met |
| `FAIL` | Neither target met |

These labels are used consistently by the dashboard (`/api/slo`), the CLI
(`--slo-report`), and the Prometheus `/metrics` endpoint.

---

## Configuration File Format

```yaml
# config/slo.yaml

services:
  - name: "e-Government Portal"
    url_contains: "turkiye.gov.tr"
    target_uptime_percent: 99.5
    target_p95_ms: 4000
    window_hours: 24

  - name: "Internal API"
    url_contains: "api.example.com"
    target_uptime_percent: 99.9
    target_p95_ms: 500
    window_hours: 1
```

**Field reference:**

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Human-readable service label |
| `url_contains` | Yes | Substring matched against target URLs |
| `target_uptime_percent` | Yes | Target uptime percentage (0 < value ≤ 100) |
| `target_p95_ms` | Yes | Target p95 latency threshold in milliseconds |
| `window_hours` | No | Evaluation window in hours (default: 24) |

---

## Running the Report

```bash
python watchdog/main.py --slo-report --last-hours 24
```

Via the API:

```
GET /api/slo
```

---

## Matching Logic

The `url_contains` field is applied as a simple substring match against
URLs recorded in the target list. If a URL matches multiple service
definitions, each service's uptime/p95 average is computed independently.

If no matching URLs are found in the given time window, or no check records
exist for that window, the service automatically falls to `FAIL`.

---

## Production Notes

- Keep SLO targets realistic. Strict p95 thresholds on public services with
  high latency variability will produce persistent `PARTIAL` alerts.
- Scale `window_hours` to monitoring frequency: a 1-hour window should
  contain at least a few dozen checks for statistically meaningful results.
- SLO evaluation relies entirely on records in the database. If the monitor
  process is not running or `WATCHDOG_DB_PATH` is misconfigured, the
  evaluation operates on zero data.
