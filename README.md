# Matbaa

PDF'ten Kindle'a dizgi tezgâhı. Elinizdeki bir kitabın PDF'ini, Kindle'da rahat okunan bir EPUB'a çevirir:
bölümleri, paragrafları, dipnotları, basılı sayfa numaralarını ve içindekileri kitabın kendisinden çıkarır;
taranmış sayfaları okur; sonucu düzenlemeniz ve Kindle'a göndermeniz için önünüze koyar.

Matbaa en çok Türkçe kitaplar için yazıldı: taranmış baskılar, yeniden dizilmiş baskılar, Türkçe heceleme ve
Türkçe bir Kindle sözlüğü.

## Ne yapar

- **Dönüştürür.** PDF'in yapısını okur: bölüm başlıkları, sayfa sonlarında bölünmüş paragraflar, dipnot ve
  sonnotlar, şekiller, içindekiler sayfası ya da PDF'in yer imleri. Taranmış ya da metni bozuk sayfaları
  Tesseract ile okur (kuruluysa).
- **Gösterir ve düzeltir.** Her dönüşümün bir raporu vardır: ne tür bir PDF'ti, Matbaa ne karar verdi,
  neyi çözemedi. Bölümleri ve paragrafları elle düzeltebilir, sonucu Kindle benzeri bir önizlemede
  görebilirsiniz.
- **EPUB'u denetler.** Her EPUB, Amazon'un "Send to Kindle" hizmetinin istediği EPUB 3 kurallarına göre
  denetlenir; geçersiz bir kitap gönderilmez.
- **Kindle'a gönderir.** Kendi e-posta hesabınızdan Kindle adresinize. Kindle USB kablosuyla bağlıyken
  Matbaa'nın yazı tiplerini ve sözlüğünü ona koyar; Kindle'daki hiçbir dosyayı silmez ya da taşımaz.
- **Okuma Defteri.** Kindle'da altını çizdikleriniz ve notlarınız, Obsidian kasanızda kitap başına bir nota
  dönüşür. Kasaya yalnız siz "Obsidian'a yaz" dediğinizde yazılır.
- **Kelime Defteri ve sözlük.** Kindle'da baktığınız kelimeler bir deftere, Vikisözlük'ten derlenen Türkçe
  bir sözlük de Kindle'a.
- **Dizin ve arama.** Basılı dizini olmayan kitaplara ad ve kavram dizini; kitabın içinde arama ve isterseniz
  kendi seçtiğiniz bir dil modeline kitaptan alıntılarla soru.
- **Tür.** Her kitabın türü (Felsefe, Siyaset, Rus edebiyatı…) Wikidata'dan ya da kitabın kendisinden
  bulunur; yanlışsa tezgâhta tek tıkla değişir. Kitaplık türlere göre sıralanır, EPUB'a da yazılır.

## Ne yapmaz

- **Kopya korumasını (DRM) kırmaz** ve kırmaya yarayan hiçbir şey içermez.
- **Kitap paylaşmaz.** Ortak bir kütüphane, yükleme sunucusu ya da kitap arama yoktur.
- Yalnız **hakkına sahip olduğunuz** kitapları kendi kullanımınız için dönüştürmeniz içindir.

## Verileriniz

Matbaa bilgisayarınızda çalışır ve verileriniz bilgisayarınızda kalır. Uzakta bir Matbaa sunucusu yoktur.

| Ne | Nerede |
|---|---|
| Dönüştürdüğünüz kitaplar | `Matbaa\projects` (ev klasörünüzde) |
| Okuma Defteri | `Matbaa\notebook` |
| Ayarlar: Obsidian kasası, Kindle e-postası, dil modeli | `.matbaa` klasöründe `obsidian.json`, `kindle.json`, `llm.json` |
| Kindle e-posta parolası | Windows'un kendi parola kasası (Kimlik Bilgileri Yöneticisi) |

Her Windows kullanıcısının kendi klasörleri vardır; aynı bilgisayarı kullanan iki kişinin kitapları ve
defterleri birbirine karışmaz. Bu klasörleri silmek Matbaa'nın sizinle ilgili tuttuğu her şeyi siler.

Yazı tipleri de dahil her şey Matbaa'nın kendi içindedir. Kendiliğinden yaptığı istekler şunlardır,
hiçbirinde kitabın metni ya da sizin adınız gitmez:

- **Kitabın türü:** dönüştürdüğünüz kitabın **adı ve yazarı** Wikidata'ya (Vikipedi'nin veri deposu)
  sorulur; yanıt gelmezse tür kitabın kendisinden tahmin edilir.
- **Açılış ekranındaki söz:** Kindle notunuz yoksa en son eklediğiniz kitabın adı ve yazarı Vikisöz'e
  sorulur, kitaptan ünlü bir söz gösterilir (kitap başına bir kez).
- **Sayaç:** dışa aktardığınız her kitabın yalnız türü, adsız olarak Matbaa'nın sitesindeki sayaca eklenir;
  açılış ekranı da sayacın toplamını siteden okur. "Hakkında ve lisanslar"dan kapatılabilir.

Bunun dışında internete yalnız siz bir şeye tıkladığınızda çıkar:

- **Künyeyi internetten tamamla:** kitabın ISBN'i Open Library'ye (gerekirse Google Books'a) gider.
- **Kindle'a gönder:** EPUB, sizin e-posta hesabınızdan Amazon'daki Kindle adresinize gider.
- **Dil modeline sor:** sorunuz ve kitaptan ilgili bölümler, anahtarını sizin girdiğiniz sağlayıcıya gider.

## Kurulum

### Tarayıcıda, kurulumsuz

[matbaa.pages.dev](https://matbaa.pages.dev)'de **Tarayıcıda başlayın**: Matbaa'nın aynı motoru tarayıcınızın içinde
çalışır (Pyodide, WebAssembly). İlk açılışta yaklaşık 40 MB iner ve tarayıcıda saklanır; kitaplarınız o
tarayıcının deposunda kalır, hiçbir sunucuya yüklenmez. Taranmış sayfaların OCR'ı, Kindle'ı kabloyla bağlamak,
Obsidian'a yazmak ve e-postayla göndermek yalnız Windows programında.

### Hazır program (Windows)

1. Sürümler (Releases) sayfasından `Matbaa.exe`'yi indirin.
2. Çift tıklayın. Program imzalı olmadığı için Windows "Bilgisayarınız korundu" diyebilir: **Ek bilgi →
   Yine de çalıştır**.
3. Matbaa tarayıcınızda `http://127.0.0.1:8765` adresinde açılır. Kapatmak için siyah pencereyi kapatın.

İsteğe bağlı programlar:

- **Taranmış kitaplar için Tesseract OCR.** Windows kurulumunda Türkçe (`tur`) dil verisini seçin.
  Matbaa onu `C:\Program Files\Tesseract-OCR` altında kendisi bulur.
- **Türkçe Kindle sözlüğü için Kindle Previewer 3** (Amazon'dan, ücretsiz). Sözlüğü Kindle biçimine
  çeviren araç onun içindedir. Matbaa bu aracı dağıtmaz.
- **EPUBCheck** için Java. Kindle Previewer kuruluysa onun içindeki Java kullanılır.

### Kaynaktan çalıştırmak

Python 3.10 ya da üstü ve Node.js 18 ya da üstü gerekir.

```bat
Matbaa.bat
```

İlk açılışta arayüzü derler ve Python ortamını kurar (birkaç dakika, internet gerekir); sonraki açılışlar
birkaç saniye sürer. Arayüzün kodunu değiştirdiyseniz `backend\app\frontend_dist` klasörünü silin ki
yeniden derlensin.

Geliştirirken iki ayrı pencerede:

```bat
cd backend
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

```bat
cd frontend
npm install
npm run dev
```

`http://localhost:5173` adresini açın; arayüz `/api` isteklerini 8000'deki sunucuya iletir.

### Tarayıcı sürümünü derlemek

`Matbaa.bat`'ı bir kez çalıştırdıktan sonra:

```bat
backend\.venv\Scripts\python tools\build_browser.py
backend\.venv\Scripts\python tools\dev_site.py
```

Sonuç `site\uygulama\` klasörüne gelir; `http://127.0.0.1:8790/uygulama/` adresinde denenir. Pyodide'ın
dosyaları ve PyMuPDF'in WebAssembly sürümü ilk derlemede indirilir ve her biri betikte sabitlenmiş SHA-256
özetiyle denetlenir.

### `Matbaa.exe`'yi kendiniz derlemek

`Matbaa.bat`'ı bir kez çalıştırdıktan sonra `build_exe.bat`. Sonuç: `backend\dist\Matbaa.exe`.

- Antivirüs programları PyInstaller ile paketlenmiş tek dosyalık programlardan bazen şüphelenir; gerekirse
  bir istisna ekleyin.
- İlk açılış birkaç saniye sürer: program kendini geçici bir klasöre açar.
- Klasör yolunda Türkçe harf varsa `pyinstaller.exe` sessizce kapanır; `build_exe.bat` bu yüzden
  `python -m PyInstaller` kullanır.

### Testler

```bat
backend\.venv\Scripts\python tools\test_api.py
```

`tools\test_*.py` dosyalarının her biri tek başına çalışır ve sonunda `ALL CHECKS PASSED` yazar. Kitapların
geneli üzerindeki ölçümler (`tools\run_qa.py`, `tools\run_library.py`) kendi kitaplarınızla çalışır; bu
depoda kitap yoktur. Testler kitaplarınızı ve defterinizi etkilemesin diye `MATBAA_PROJECTS` ve
`MATBAA_NOTEBOOK` ile geçici bir klasör gösterin.

## Güvenlik

- Matbaa'nın yerel sunucusu yalnız bu bilgisayardan (`127.0.0.1`) gelen bağlantıları dinler.
- Başka bir alan adıyla gelen istekleri ve değişiklik yapan isteklerden Matbaa'nın kendi sayfasından
  gelmeyenleri reddeder. Böylece açık bir web sitesi, tarayıcınız üzerinden Matbaa'ya bir şey yaptıramaz.
- Bir güvenlik açığı bulursanız lütfen herkese açık bir konu (issue) açmayın; deponun **Security**
  sekmesinden özel olarak bildirin.

## Lisans

Matbaa özgür yazılımdır: GNU Affero Genel Kamu Lisansı sürüm 3 (AGPL-3.0) ile dağıtılır (`LICENSE`).
Üzerine kurulduğu yazılımlar, yazı tipleri ve verilerin lisansları: `THIRD-PARTY-LICENSES.md`.

Kindle ve Amazon, Amazon.com, Inc. ya da bağlı şirketlerinin markalarıdır. Obsidian, Dynalist Inc.'in
markasıdır. Matbaa bu şirketlerle ilişkili değildir ve onlar tarafından onaylanmamıştır.
