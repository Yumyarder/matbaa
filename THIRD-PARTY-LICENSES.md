# Üçüncü taraf lisansları

Matbaa, aşağıdaki yazılımların, yazı tiplerinin ve verilerin üzerine kuruludur. Her biri kendi lisansıyla
gelir; lisans metinleri paketlerin kendi içindedir (Python paketlerinde `*.dist-info/`, npm paketlerinde
`node_modules/<paket>/LICENSE`, yazı tiplerinde yanlarındaki `OFL.txt`).

Matbaa'nın kendisi GNU Affero Genel Kamu Lisansı sürüm 3 (AGPL-3.0) ile dağıtılır, çünkü üzerine kurulduğu
PDF motoru (PyMuPDF) ve EPUB kitaplığı (EbookLib) bu lisansla gelir. Ayrıntı için `LICENSE` dosyasına bakın.

## Python paketleri (Matbaa.exe'nin içinde)

| Paket | Sürüm | Lisans |
|---|---|---|
| PyMuPDF, PyMuPDFb (Artifex Software) | 1.24.5 | GNU AGPL-3.0 |
| EbookLib (Aleksandar Erkalović) | 0.18 | GNU AGPL-3.0 |
| FastAPI | 0.162.0 | MIT |
| Starlette | 1.10.0 | BSD-3-Clause |
| Uvicorn | 0.54.0 | BSD-3-Clause |
| Pydantic, pydantic-core | 2.14.1, 2.50.1 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| Pillow | 13.0.0 | HPND |
| pytesseract | 0.3.13 | Apache-2.0 |
| fontTools | 4.67.0 | MIT |
| keyring | 25.6.0 | MIT |
| lxml | 6.1.1 | BSD-3-Clause |
| anyio, h11, httptools | — | MIT |
| httpx, httpcore, idna, click, MarkupSafe, python-dotenv, websockets, ujson | — | BSD-3-Clause (ujson: BSD-3-Clause ve TCL) |
| Jinja2, colorama | — | BSD |
| Pygments | 2.20.0 | BSD-2-Clause |
| packaging | 26.2 | Apache-2.0 ya da BSD-2-Clause |
| orjson | 3.11.9 | MPL-2.0 ve (Apache-2.0 ya da MIT) |
| certifi | 2026.10.23 | MPL-2.0 |
| dnspython, shellingham | — | ISC |
| email-validator | 2.3.0 | Unlicense |
| typing-extensions | 4.16.0 | PSF-2.0 |
| annotated-types, annotated-doc, jaraco.*, markdown-it-py, mdurl, more-itertools, PyYAML, rich, rich-toolkit, six, typer, watchfiles, fastapi-cli | — | MIT |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause |
| Python (yorumlayıcının kendisi) | 3.x | PSF License |

`Matbaa.exe`, PyInstaller ile paketlenir. PyInstaller'ın önyükleyicisi GPL'dir, ama paketlenen programa
lisans yüklemeyen özel bir istisnayla gelir.

## Arayüz (tarayıcıda çalışan kısım)

| Paket | Sürüm | Lisans |
|---|---|---|
| React, React DOM, scheduler (Meta ve katkıcılar) | 18.3.1 | MIT |
| loose-envify, js-tokens | — | MIT |
| Vite, @vitejs/plugin-react (yalnız derlemede) | 5.x | MIT |

## Tarayıcı sürümü (matbaa.pages.dev/uygulama/)

Aynı Python kodu ve aynı arayüz, tarayıcıda WebAssembly üzerinde çalışır. Siteden şunlar dağıtılır
(`tools/build_browser.py` her dosyayı sabitlenmiş SHA-256 özetiyle denetler):

| Paket | Sürüm | Lisans |
|---|---|---|
| Pyodide (CPython 3.13'ün WebAssembly yapımı ve Emscripten çalışma ortamıyla) | 0.29.4 | MPL-2.0 (CPython: PSF License; Emscripten: MIT / NCSA) |
| PyMuPDF (Artifex Software, WebAssembly yapımı) | 1.28.2 | GNU AGPL-3.0 |
| EbookLib | 0.18 | GNU AGPL-3.0 |
| lxml | 6.0.2 | BSD-3-Clause |
| Pillow | 11.3.0 | HPND |
| fontTools | 4.56.0 | MIT |
| FastAPI, Starlette, Pydantic, pydantic-core, anyio, httpx | Pyodide 0.29.4'teki sürümler | MIT / BSD-3-Clause |
| Jinja2, MarkupSafe | Pyodide 0.29.4'teki sürümler | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| six, sniffio, annotated-types, typing-inspection, pyodide-http | Pyodide 0.29.4'teki sürümler | MIT (sniffio: MIT ya da Apache-2.0) |
| typing-extensions | 4.15.0 | PSF-2.0 |
| SQLite | Pyodide 0.29.4'teki sürüm | Kamu malı |
| OpenSSL | 1.1.1w | OpenSSL ve SSLeay lisansları |

## Yazı tipleri

| Yazı tipi | Kimin | Lisans | Nerede |
|---|---|---|---|
| EB Garamond | The EB Garamond Project Authors | SIL Open Font License 1.1 | Haşiye arayüzü, site |
| Literata | The Literata Project Authors | SIL Open Font License 1.1 | Kindle'a konan yazı tipi, istenirse kitaba gömülür |
| Charis | SIL Global ("Charis" ve "SIL" ayrılmış adlardır) | SIL Open Font License 1.1 | Kindle'a konan yazı tipi |

Bir kitaba yazı tipi gömüldüğünde yalnız o kitapta geçen harfler alınır. OFL'nin SSS'si (1.12) belgeye
gömülen alt kümeye izin verir; yazı tipi o belgenin dışında kullanılmaz.

## Programlar (Matbaa'nın içinde değil, bilgisayarınızda kuruluysa kullanılır)

| Program | Lisans | Ne için |
|---|---|---|
| Tesseract OCR (`tur`, `eng` dil verisiyle) | Apache-2.0 | Taranmış sayfaları okumak |
| EPUBCheck (W3C) | BSD-3-Clause | EPUB'u Amazon'un ölçütüyle denetlemek |
| Kindle Previewer / kindlegen (Amazon) | Amazon'un kendi lisansı | Türkçe sözlüğü Kindle biçimine çevirmek |

kindlegen Matbaa ile dağıtılmaz ve bir sunucuda çalıştırılmaz; yalnız sizin bilgisayarınızda kurulu
Kindle Previewer'ın içindeki kopya kullanılır.

## Veriler

| Veri | Kaynak | Lisans |
|---|---|---|
| Türkçe sözlük | Vikisözlük katkıcıları, wiktextract ile çıkarılmış hali (kaikki.org) | CC BY-SA |
| `backend/app/data/tr_words.tsv` | Türkçe kitaplardan sayılmış tek tek kelimeler ve sıklıkları; hiçbir kitabın metni yok | Matbaa ile aynı (AGPL-3.0) |
| Künye araması | Open Library, Google Books (yalnız tıklayınca, yalnız ISBN gider) | Hizmetlerin kendi kullanım koşulları |
| Kitabın türü | Wikidata (dönüştürürken kitabın adı ve yazarı sorulur) | CC0 (veri); Wikimedia kullanım koşulları |
| Açılış ekranındaki söz | Vikisöz / Wikiquote (kaynağıyla ve bağlantısıyla gösterilir) | CC BY-SA |

Kindle'a konan sözlük Vikisözlük metinlerinden derlenir ve aynı lisansla (CC BY-SA) paylaşılır.

## Markalar

Kindle ve Amazon, Amazon.com, Inc. ya da bağlı şirketlerinin markalarıdır. Obsidian, Dynalist Inc.'in
markasıdır. Matbaa bu şirketlerle ilişkili değildir ve onlar tarafından onaylanmamıştır; adlarını yalnız
hangi araçlarla birlikte çalıştığını söylemek için kullanır.

`frontend/src/assets/obsidian-logo-gradient.svg` Obsidian'ın logosudur: obsidian.md/brand sayfasındaki
hâliyle, değiştirilmeden ve yeniden renklendirilmeden, yalnız Okuma Defteri'nde Obsidian adının yanında
durur. Matbaa'nın AGPL lisansı bu dosyayı kapsamaz; Obsidian isterse kaldırılır.
