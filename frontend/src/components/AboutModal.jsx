import React, { useEffect, useState } from "react";
import pkg from "../../package.json";
import { fetchCounter, saveCounter } from "../api";

// About and licences: where the source is (Matbaa is AGPL-3.0 because the
// engine it is built on is), what happens to the reader's data, what the
// app will not do, and whose work and marks it uses. Opened from the look
// switch strip, so both design languages carry it.
export const SOURCE_URL = "https://github.com/Yumyarder/matbaa";

const PARTS = [
  ["PyMuPDF", "Artifex Software", "GNU AGPL-3.0"],
  ["EbookLib", "Aleksandar Erkalović", "GNU AGPL-3.0"],
  ["FastAPI, Pydantic, Uvicorn", "", "MIT / BSD"],
  ["React, Vite", "Meta ve katkıcılar", "MIT"],
  ["Tesseract OCR", "Google ve katkıcılar", "Apache 2.0"],
  ["EB Garamond, Literata, Charis", "Georg Duffner; TypeTogether; SIL", "SIL Open Font License 1.1"],
  ["Türkçe sözlük verisi", "Vikisözlük katkıcıları, wiktextract (kaikki.org)", "CC BY-SA"],
  ["Künye araması", "Open Library, Google Books", "Kendi kullanım koşulları"],
  ["Kitabın türü", "Wikidata", "CC0"],
];

export default function AboutModal({ onClose }) {
  const [count, setCount] = useState(null);
  useEffect(() => { fetchCounter().then(setCount).catch(() => setCount(null)); }, []);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-overlay" role="presentation" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-panel modal-panel--wide about" role="dialog" aria-modal="true" aria-labelledby="about-title">
        <h2 id="about-title">Matbaa · sürüm {pkg.version}</h2>
        <p className="modal-panel__hint">PDF kitaplarınızı Kindle'da düzgün okunan EPUB'lara dizer; Kindle'daki
          vurgularınızı ve kelimelerinizi Obsidian kasanıza taşır.</p>

        <h3 className="about__head">Verileriniz</h3>
        <p className="about__text">Kitaplarınız, notlarınız, kelimeleriniz ve ayarlarınız yalnız bu bilgisayarda,
          sizin kullanıcı klasörünüzde durur. Yeni bir kitabın türü için Matbaa kitabın adını ve yazarını
          Wikidata'ya, açılış ekranındaki söz için en son kitabınızınkini Vikisöz'e sorar; dışa aktardığınız her
          kitabın yalnız türünü, adsız olarak sitedeki sayaca ekler ve sayacın toplamını oradan okur. ISBN
          araması, dil modeline soru ve Kindle'a e-posta yalnız sizin tıklamanızla olur.</p>
        {count?.active && (
          <label className="about__toggle">
            <input type="checkbox" checked={!!count.enabled}
                   onChange={(e) => saveCounter({ enabled: e.target.checked, notice_seen: true })
                     .then(setCount).catch(() => {})} />
            Dışa aktardığım kitapların türünü sitedeki sayaca ekle
          </label>
        )}

        <h3 className="about__head">Kitaplar</h3>
        <p className="about__text">Yalnız hakkına sahip olduğunuz kitapları dönüştürün. Matbaa kopya korumasını
          (DRM) kırmaz; korumalı dosyaları açmaz. Yayıncının metin kopyalamayı kapattığı ya da parolayla kilitlediği
          PDF'leri de dönüştürmez.</p>

        <h3 className="about__head">Kaynak kodu</h3>
        <p className="about__text">Matbaa özgür yazılımdır: GNU Affero Genel Kamu Lisansı sürüm 3 (AGPL-3.0)
          altında dağıtılır.{" "}
          {SOURCE_URL
            ? <>Kaynak kodu: <a href={SOURCE_URL} target="_blank" rel="noreferrer">{SOURCE_URL}</a>.</>
            : "Kaynak kodu yayımlandığında bağlantısı burada olacak."}
          {" "}Garanti verilmez.</p>

        <h3 className="about__head">Kullandığı yazılımlar ve veriler</h3>
        <table className="about__table">
          <tbody>
            {PARTS.map(([what, who, licence]) => (
              <tr key={what}>
                <th scope="row">{what}</th>
                <td>{who}</td>
                <td>{licence}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3 className="about__head">Markalar</h3>
        <p className="about__text">Kindle ve Amazon, Amazon.com, Inc. ya da bağlı şirketlerinin markalarıdır.
          Obsidian, Dynalist Inc.'in markasıdır. Matbaa bu şirketlerle ilişkili değildir ve onlar tarafından
          onaylanmamıştır; adları yalnız uyumluluğu anlatmak için kullanılır.</p>

        <div className="modal-actions">
          <button type="button" className="btn btn--primary" onClick={onClose}>Kapat</button>
        </div>
      </div>
    </div>
  );
}
