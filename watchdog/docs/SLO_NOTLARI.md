## WatchDog – Örnek SLO Tanımları

Bu dosya, kritik bazı endpointler için örnek uptime ve latency SLO
hedeflerini içerir. Amaç, ileride SLO/error‑budget katmanını
uygularken referans olmalarıdır. Çalışan konfigürasyon dosyası
`config/slo.yaml` içinde tutulur; burada yer alan değerlerle
uyumlu olacak şekilde düzenlenmelidir.

### 1. Cumhurbaşkanlığı (T.C. Resmi Sitesi)

- URL: `https://www.tccb.gov.tr`
- Uptime hedefi: **≥ 99.0 %** (aylık)
- p95 latency hedefi: **≤ 5000 ms**

### 2. e‑Devlet Kapısı

- URL: `https://www.turkiye.gov.tr`
- Uptime hedefi: **≥ 99.5 %**
- p95 latency hedefi: **≤ 4000 ms**

### 3. TBMM

- URL: `https://www.tbmm.gov.tr`
- Uptime hedefi: **≥ 99.0 %**
- p95 latency hedefi: **≤ 6000 ms**

### 4. TSE (örnek kamu standardizasyon kurumu)

- URL: `https://www.tse.org.tr`
- Uptime hedefi: **≥ 98.5 %**
- p95 latency hedefi: **≤ 7000 ms**

### 5. Genişletilmiş kamu seti (public_institutions_expanded)

- Küme bazında hedef:
  - Uptime hedefi: **≥ 97.0 %** (yüksek sayıda hedef ve yoğun DNS/SSL
    sorunları nedeniyle daha esnek)
  - p95 latency hedefi: **≤ 12000 ms**

### 6. PARTIAL durumu (kısmi SLO tutturma)

WatchDog SLO değerlendirmesi üç olası durum üretir:

- `PASS`: Hem uptime hem de p95 latency hedefi tutturulmuş.
- `PARTIAL`: Hedeflerden yalnızca biri (uptime veya p95 latency) tutturulmuş.
- `FAIL`: Hiçbiri tutturulamamış.

Dashboard ve `/api/slo` çıktısı bu üç değeri kullanır; `PARTIAL` durumları
kartlarda sarı uyarı rengiyle vurgulanır.

