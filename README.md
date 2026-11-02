# BRAWLIX — Otomatik Rakip Eşleştirme Sunucusu

Bu klasör, HIZLI OYNA'nın **gerçek** sunucu tarafıdır: oyuncuları seviyeye
göre eşleştiren küçük bir "bilet" servisi. Oyunun kendisi zaten hazır — bu
sunucu deploy edilip adresi oyuna yazıldığı an gerçek yabancı eşleşmesi
canlanır. Sunucu kurulana kadar oyun sahte bir eşleşme göstermez; arama
ekranı "servis bağlı değil" der ve kod/davet akışıyla oynar.

**Ne yapar:** HIZLI OYNA'ya basan oyuncu kendi maç odasını kurar ve
kimlik+seviye+oda kodu bilgisini buraya bırakır. İki uygun oyuncu bir araya
gelince sunucu ikisine de aynı oda kodunu verir; ikisi de otomatik olarak
aynı maça girer. Kurallar: aynı oyuncu tek kuyrukta kalır, kendisiyle
eşleşemez, bilet tek kullanımlıktır, bağlantısı kopan oyuncunun kaydı 30
saniyede düşer, seviye aralığı bekledikçe genişler (2 → 4 → 8).

---

## 1. Sunucuyu yayınlama (iki yol)

### Yol A — Railway (en hızlı, GitHub gerekmez, ~5 dakika)

1. [railway.app](https://railway.app) → GitHub ile giriş yap (ücretsiz hesap).
2. Terminal aç ve şunları sırayla çalıştır:
   ```
   npm install -g @railway/cli
   railway login
   cd matchmaking-server        (bu klasör)
   railway init                 (proje adı: brawlix-match)
   railway up
   ```
3. Railway panelinde → Settings → Networking → **Generate Domain** →
   `https://brawlix-match-production.up.railway.app` gibi bir adres verir.
4. Doğrula: adresi tarayıcıda aç → `{"service":"brawlix-matchmaker","ok":true}`
   görmelisin. `/health` de aynı şekilde çalışır.

### Yol B — Render (ücretsiz katman var, GitHub ister)

1. `matchmaking-server/` klasörünü bir GitHub deposuna yükle (deponun kökünde
   `render.yaml` bulunsun — bu klasörle birlikte geliyor).
2. [render.com](https://render.com) → New + → **Blueprint** → depoyu seç.
3. Render `render.yaml`'ı okur: Python servisi, derleme
   `pip install -r requirements.txt`, başlatma `uvicorn main:app ...`.
4. Deploy bitince Render sana `https://brawlix-matchmaker.onrender.com`
   gibi bir adres verir. Tarayıcıda açıp `{"ok":true}` yanıtını gör.

> Ücretsiz Render planı kullanılmadığında uykuya yatar; ilk arama ~30-60 sn
> gecikmeli başlar (sunucu "ısınıyor"). Kesintisiz arama için ücretli plan.

---

## 2. Sunucu adresi oyuna nereden girilir

Tek satır:

```
scripts/autoloads/net_manager.gd   →   var matchmaker_url: String = ""
```

Bu satırdaki `""` yerine kendi adresini tırnak içinde yaz:

```gdscript
var matchmaker_url: String = "https://brawlix-match-production.up.railway.app"
```

Kurallar: adresin **sonunda `/` olmasın** (sunucu `.../queue/join` şeklinde
ekler). Sonra oyunu bir kez yeniden derlemek yeterli — menüdeki HIZLI OYNA
artık gerçek kuyruğu kullanır ve arama ekranındaki "servis bağlı değil"
uyarısı kaybolur.

---

## 3. Sunucunun ihtiyaçları ve maliyet

| Gereksinim | Değer |
|---|---|
| Kapasite | 1 küçük konteyner, ~%5 CPU, ~100 MB RAM |
| Veritabanı | Gerekmez (kuyruk bellekte, 30 sn ömürlü) |
| Bağlantı | Yalnızca HTTPS; WebSocket yok |
| Ölçek | Tek süreç şart (kuyruk bellekte yaşar); aynı anda binlerce aramaya yeter |

**Maliyet seçenekleri:**
- **Render Free** — 0 TL. Dezavantaj: boşta uyku + ilk aramada 30-60 sn ısınma.
- **Render Starter** — ~$7/ay. Hiç uyumaz, arama anında başlar.
- **Railway Hobby** — $5/ay kredi. Bu servisin tüm aylık tüketimi ~$1-2 civarı
  kalır (küçük CPU/RAM).
- Oyuncu sayısı çok artarsa aynı sunucu yine çalışır; bellek tutmaya
  başlayınca Redis'e taşımak gerekir (şimdilik gereksiz).

---

## 4. Kurulum sonrası test (iki gerçek oyuncu)

1. İki ayrı cihazda (veya iki tarayıcı penceresinde) oyunu aç.
2. **Hızlı oyna**'ya ikiniz de basın → her iki ekranda "RAKİP ARANIYOR"
   görür, birkaç saniye içinde "RAKİP BULUNDU" yazar ve ikiniz de **aynı
   arenada** buluşursunuz. (Seviyeler çok farklıysa ilk eşleşme ~20 sn
   sürebilir: arama aralığı kademeli genişler.)
3. İptal testi: biri İPTAL'e basar → kuyruğu temizlenir; tekrar basabilir.
4. Kopma testi: arama sırasında birinin sekmesini kapat → 30 sn içinde
   kaydı düşer; diğeri aramaya devam eder, hayalet eşleşme oluşmaz.
5. Kimlik testi: aynı cihazda iki sekme HIZLI OYNA'ya basarsa yalnızca biri
   kuyruktadır — oyuncu kendi kendisiyle asla eşleşemez.

---

## 5. Sorun giderme

| Belirti | Sebep / çözüm |
|---|---|
| Oyun "servise ulaşılamadı (http_404)" diyor | Adres yanlış veya sonunda `/` var; 2. bölümdeki satırı kontrol et |
| Tarayıcıda `{ok:true}` var ama oyun bağlanmıyor | Oyun hâlâ eski derleme — adresi yazdıktan sonra yeniden derle |
| İlk arama çok bekliyor | Render free plan uykudan uyanıyor (~60 sn); bir kez oldu mu normale döner |
| "Arama odası kurulamadı" | Bu, oyunun oda sunucusundaki (mp.tesana.ai) bağlantısıdır; eşleştirme sunucun değil — interneti kontrol et |
| Sunucu yeniden başladı, kuyruk boşaldı | Beklenen davranış: kuyruk bellekte tutulur; oyuncular tekrar HIZLI OYNA'ya basar |

---

## 6. Dosyalar

| Dosya | Görev |
|---|---|
| `queue_core.py` | Eşleştirme kurallarının tamamı (saf mantık, bağımlılıksız) |
| `main.py` | HTTP uç noktaları (join / status / cancel / widen / health) |
| `requirements.txt` | fastapi + uvicorn |
| `Procfile` | Railway/Heroku başlatma komutu |
| `render.yaml` | Render tek tıkla kurulum tanımı |
